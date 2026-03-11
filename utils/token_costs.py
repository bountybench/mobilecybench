"""Utilities for loading and using token pricing information.

This module provides functionality to load token pricing data from a JSON file,
retrieve pricing information for specific models, and compute costs based on token usage.

"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Dict, Optional

from utils.logger import logger


@dataclass(frozen=True)
class HighContextPricing:
    """Tiered pricing that applies when input tokens exceed a threshold.

    Some models (e.g. GPT-5.4) charge higher rates once the prompt exceeds
    a token count threshold.  When the threshold is crossed, *all* tokens
    in the request are billed at the higher rate (not just the excess).
    """

    input_threshold: int  # token count that triggers the higher tier
    input: float = 0.0
    output: float = 0.0
    cache_input: float = 0.0


@dataclass(frozen=True)
class ModelPricing:
    """Per-1M token pricing for a model.

    All values are USD per 1,000,000 tokens.
    Missing fields default to 0.0.

    Attributes:
        - input: Price per 1M input tokens.
        - output: Price per 1M output tokens.
        - cache_input: Price per 1M cache-read input tokens.
        - high_context: Optional higher-tier pricing for long prompts.
    """

    input: float = 0.0
    output: float = 0.0
    cache_input: float = 0.0
    high_context: Optional[HighContextPricing] = None


def _parse_pricing_map(raw: Dict[str, dict]) -> Dict[str, ModelPricing]:
    """Parse raw JSON dictionary into a mapping of model strings to ModelPricing.

    Args:
        raw: Raw dictionary from loaded JSON.
             Expected format:
                {
                    "model_name": {
                        "input": <input_price>,
                        "output": <output_price>,
                        "cache_input": <cache_input_price>
                    },
                    ...
                }
    Returns:
        Dictionary mapping model names to ModelPricing instances.
    """
    parsed: Dict[str, ModelPricing] = {}
    for model_name, price_entry in (raw or {}).items():
        if not isinstance(price_entry, dict):
            continue
        high_context = None
        high_context_entry = price_entry.get("high_context")
        if (
            isinstance(high_context_entry, dict)
            and "input_threshold" in high_context_entry
        ):
            high_context = HighContextPricing(
                input_threshold=int(high_context_entry["input_threshold"]),
                input=float(high_context_entry.get("input", 0) or 0),
                output=float(high_context_entry.get("output", 0) or 0),
                cache_input=float(high_context_entry.get("cache_input", 0) or 0),
            )
        parsed[model_name] = ModelPricing(
            input=float(price_entry.get("input", 0) or 0),
            output=float(price_entry.get("output", 0) or 0),
            cache_input=float(price_entry.get("cache_input", 0) or 0),
            high_context=high_context,
        )
    return parsed


def load_pricing(path: Optional[str] = None) -> Dict[str, ModelPricing]:
    """Load pricing configuration from a JSON file.

    Args:
        path: path to the JSON pricing file. Default to `utils/token_pricing.json` if present.
    Returns:
        - Dictionary mapping model names to ModelPricing instances.
        - Empty dictionary if loading fails.
    Raises:
        - No exceptions; logs warnings and returns empty dict on failure.
        - This is to continue tracking tokens and avoid breaking the pipeline if pricing is unavailable.
    """
    if path is None:
        candidate = os.path.join(os.path.dirname(__file__), "token_pricing.json")
        path = candidate if os.path.exists(candidate) else None

    if not path:
        logger.warning("No pricing file found in path %s", path)
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.warning("Pricing JSON is not an object/dict: %s", path)
            return {}
        return _parse_pricing_map(data)
    except FileNotFoundError:
        logger.warning("Pricing file not found: %s", path)
        return {}
    except json.JSONDecodeError as e:
        logger.warning("Invalid JSON in pricing file %s: %s", path, e)
        return {}
    except Exception as e:
        logger.warning("Failed to load pricing JSON %s: %s", path, e)
        return {}


def _strip_provider_prefix(model: str) -> str:
    """Strip provider prefix from model name if present.

    LiteLLM uses prefixes like "gemini/", "anthropic/" to route to providers.
    We need to strip these for pricing lookup.

    Args:
        model: Model name that may contain a provider prefix.

    Returns:
        Model name without provider prefix.

    Examples:
        "gemini/gemini-3-pro-preview" -> "gemini-3-pro-preview"
        "gpt-5.2" -> "gpt-5.2" (unchanged)
    """
    if "/" in model:
        return model.split("/", 1)[1]
    return model


def _strip_date_suffix(model: str) -> str:
    """Strip date suffix from model name if present.

    Args:
        model: Model name that may contain a date suffix like "-2025-08-07".

    Returns:
        Model name without date suffix.

    Examples:
        "gpt-5-2025-08-07" -> "gpt-5"
        "gpt-5-mini-2025-08-07" -> "gpt-5-mini"
        "gpt-4" -> "gpt-4" (unchanged)
    """
    # Pattern matches "-YYYY-MM-DD" at the end of the string
    date_pattern = r"-\d{4}-\d{2}-\d{2}$"
    return re.sub(date_pattern, "", model)


def get_pricing_for_model(
    model: str,
    pricing_map: Optional[Dict[str, ModelPricing]] = None,
    *,
    warn: bool = True,
) -> ModelPricing:
    """Get pricing for a specific model.

    Args:
        model: Model name to look up.
        pricing_map: Optional pre-loaded pricing map. If None, loads from default path.

    Returns:
        ModelPricing instance. Returns all-zero pricing for unknown models to prevent
        pipeline failures.

    Note:
        Lookup order:
        1. Exact model name match
        2. With provider prefix stripped (e.g., "gemini/gemini-2.0-flash" -> "gemini-2.0-flash")
        3. With date suffix stripped (e.g., "gpt-5-2025-08-07" -> "gpt-5")
        4. With both prefix and date suffix stripped

        If still unknown and `warn` is True, a warning is logged.
        Returns ModelPricing with all zeros to avoid breaking the pipeline.
    """
    all_pricing = pricing_map if pricing_map is not None else load_pricing()

    # Try exact match first
    pricing = all_pricing.get(model)
    if pricing is not None:
        return pricing

    # Try with provider prefix stripped (e.g., "gemini/gemini-2.0-flash" -> "gemini-2.0-flash")
    model_no_prefix = _strip_provider_prefix(model)
    if model_no_prefix != model:
        pricing = all_pricing.get(model_no_prefix)
        if pricing is not None:
            logger.debug(f"Using pricing for '{model_no_prefix}' for model '{model}'")
            return pricing

    # Try with date suffix stripped
    model_no_date = _strip_date_suffix(model_no_prefix)
    if model_no_date != model_no_prefix:
        pricing = all_pricing.get(model_no_date)
        if pricing is not None:
            logger.debug(f"Using pricing for '{model_no_date}' for model '{model}'")
            return pricing

    # No pricing found
    if warn:
        logger.warning(f"Token pricing unknown for model '{model}'; using zeros.")
    return ModelPricing()  # all pricing zeros


def compute_cost_usd(
    pricing: ModelPricing,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_input_tokens: int = 0,
) -> float:
    """Calculate the USD cost based on token usage and model pricing.

    Args:
        pricing: ModelPricing instance with per-1M token prices.
        input_tokens: Number of input tokens used.
        output_tokens: Number of output tokens generated.
        cache_input_tokens: Number of input tokens served from cache.

    Returns:
        - Cost in USD as a float. (non-negative)
    """
    it = max(int(input_tokens or 0), 0)
    ot = max(int(output_tokens or 0), 0)
    ci = max(int(cache_input_tokens or 0), 0)
    billed_input = max(it - ci, 0)

    # Select tier: if high-context pricing exists and input exceeds threshold,
    # the entire request is billed at the higher rate.
    high_ctx = pricing.high_context
    if high_ctx and it > high_ctx.input_threshold:
        rate = high_ctx
    else:
        rate = pricing

    scale = 1_000_000.0
    cost_input = (billed_input / scale) * rate.input
    cost_output = (ot / scale) * rate.output
    cost_cache_input = (ci / scale) * rate.cache_input
    return float(cost_input + cost_output + cost_cache_input)
