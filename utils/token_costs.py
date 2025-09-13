"""Utilities for loading and using token pricing information.

This module provides functionality to load token pricing data from a JSON file,
retrieve pricing information for specific models, and compute costs based on token usage.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, Optional

from utils.logger import logger


@dataclass(frozen=True)
class ModelPricing:
    """Per-1M token pricing for a model.

    All values are USD per 1,000,000 tokens.
    Missing fields default to 0.0.

    Attributes:
        - input: Price per 1M input tokens.
        - output: Price per 1M output tokens.
        - cache_input: Price per 1M cache-read input tokens.
    """

    input: float = 0.0
    output: float = 0.0
    cache_input: float = 0.0


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
    for model, vals in (raw or {}).items():
        if not isinstance(vals, dict):
            continue
        parsed[model] = ModelPricing(
            input=float(vals.get("input", 0) or 0),
            output=float(vals.get("output", 0) or 0),
            cache_input=float(vals.get("cache_input", 0) or 0),
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
        For now, only exact model names are supported (no prefix matching).
        If unknown and `warn` is True, a warning is logged. Returns a ModelPricing
        with all zeros to avoid breaking the pipeline.
        TODO: support prefix matching in future. (e.g. "gpt-5" matches "gpt-5-2025-__-__")
    """
    pm = pricing_map if pricing_map is not None else load_pricing()
    pricing = pm.get(model)
    if pricing is None:
        if warn:
            logger.warning(f"Token pricing unknown for model '{model}'; using zeros.")
        return ModelPricing()  # all pricing zeros
    return pricing


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

    Note:
        TODO: check the logic here matches actual provider billing
    """
    it = max(int(input_tokens or 0), 0)
    ot = max(int(output_tokens or 0), 0)
    ci = max(int(cache_input_tokens or 0), 0)
    billed_input = max(it - ci, 0)

    scale = 1_000_000.0
    cost_input = (billed_input / scale) * pricing.input
    cost_output = (ot / scale) * pricing.output
    cost_cache_input = (ci / scale) * pricing.cache_input
    return float(cost_input + cost_output + cost_cache_input)
