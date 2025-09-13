"""Token usage tracking and cost calculation for API calls.

This module defines a TokenTracker class that can record token usage from
OpenAI-like response objects, compute costs based on a pricing map, and maintain
aggregated totals. It supports logging usage records to a JSONL file for detailed
analysis.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from utils.logger import logger
from utils.token_costs import (
    ModelPricing,
    compute_cost_usd,
    get_pricing_for_model,
    load_pricing,
)


@dataclass
class TokenUsage:
    """A normalized record of tokens and cost for a single API call.

    Attributes:
        - model: The model name used for the API call.
        - request_id: The unique request ID from the API response, if available.
        - created_at: timestamp when the record was created.
        - input_tokens: Number of input tokens used.
        - output_tokens: Number of output tokens generated.
        - cache_input_tokens: Number of input tokens served from cache.
        - cost_usd: Total cost in USD for this call, rounded to 10 decimal places.
    """
    model: str
    request_id: Optional[str]
    created_at: str
    input_tokens: int
    output_tokens: int
    cache_input_tokens: int
    cost_usd: float


def _extract_token_count(u: Any, key: str, default: int = 0) -> int:
    """Safely extract token counts from API response usage object.

    Args:
        u: The usage object from the API response.
        key: One of "input_tokens", "output_tokens", or "cache_input_tokens".
        default: Value to return if the key is not found or extraction fails.
    Returns:
        Integer token count for the specified key, or default if not found.
    Note:
        OpenAI Python SDK reference:
        - https://github.com/openai/openai-python/blob/main/src/openai/types/responses/response.py
        - https://github.com/openai/openai-python/blob/main/src/openai/types/responses/response_usage.py
    """
    if u is None:
        return default
    try:
        if key == "cache_input_tokens":
            details = getattr(u, "input_tokens_details", None)
            if details and hasattr(details, "cached_tokens"):
                val = getattr(details, "cached_tokens")
                return int(val) if val is not None else default
            return default
        else:  # input_tokens or output_tokens
            if hasattr(u, key):
                val = getattr(u, key)
                return int(val) if val is not None else default
    except Exception:
        pass
    return default


def _extract_usage_openai_like(resp: Any) -> Tuple[int, int, int, Optional[str]]:
    """Extract token usage and request ID from OpenAI-compatible API response.

    Args:
        resp: The response object from an OpenAI-like API call.
    Returns:
        A tuple of (input_tokens, output_tokens, cache_input_tokens, request_id).
        Each token count defaults to 0 if not found, and request_id may be None.
    Note:
        Expected response structure:
        {
            "id": "some-id",
            "usage": {
                "input_tokens": 60204,
                "input_tokens_details": {
                    "cached_tokens": 56192
                },
                "output_tokens": 7706,
                "output_tokens_details": {
                    "reasoning_tokens": 3776
                },
                "total_tokens": 67910
            },
            "other fields": ...
    """
    request_id = getattr(resp, "id", None)
    usage: Optional[Any] = getattr(resp, "usage", None)
    input_tokens = _extract_token_count(usage, "input_tokens", 0)
    output_tokens = _extract_token_count(usage, "output_tokens", 0)
    cache_read = _extract_token_count(usage, "cache_input_tokens", 0)

    return input_tokens, output_tokens, cache_read, request_id


class TokenTracker:
    """Tracks and aggregates token usage and costs across multiple API calls.

    This class maintains running totals of token usage and costs.

    Attributes:
        - total_input_tokens: Cumulative input tokens across all recorded calls.
        - total_output_tokens: Cumulative output tokens across all recorded calls.
        - total_cache_input_tokens: Cumulative cache-read input tokens across all calls.
        - total_cost_usd: Cumulative cost in USD across all recorded calls.
        - call_count: Total number of API calls recorded.

    Example usage:
        >>> tracker = TokenTracker(pricing_path="custom_pricing.json")
        >>> record = tracker.record_from_openai_response(api_response, "gpt-4.1")
        >>> print(tracker.totals())
        {'calls': 1, 'input_tokens': 1000, 'output_tokens': 500, ...}
    """

    def __init__(
        self,
        *,
        pricing_path: Optional[str] = None,
        jsonl_path: Optional[str] = None,
    ) -> None:
        """Initialize the TokenTracker.
        Args:
            - pricing_path: optional path to a JSON file with model pricing data.
                * If None, uses default location from token_costs module.
            - jsonl_path: Optional path to a JSONL file to append detailed usage records.
                * If None, defaults to "token_usage.jsonl" in the current directory.
                * If set to an empty string, no file will be written.
        """
        self._pricing_map = load_pricing(pricing_path)
        self._jsonl_path = jsonl_path if jsonl_path else "token_usage.jsonl"

        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cache_input_tokens = 0
        self.total_cost_usd = 0.0
        self.call_count = 0
    
    def _update_totals(self, record: TokenUsage) -> None:
        """Update running totals with data from a new usage record."""
        self.total_input_tokens += record.input_tokens
        self.total_output_tokens += record.output_tokens
        self.total_cache_input_tokens += record.cache_input_tokens
        self.total_cost_usd += record.cost_usd
        self.call_count += 1

    def record_from_openai_response(self, resp: Any, model: str) -> TokenUsage:
        """Record token usage from an OpenAI-like API response.

        Extracts token usage data from the response, calculates cost using
        the configured pricing data, updates running totals.

        Args:
            resp: The response object from an OpenAI-like API call.
            model: The model name used for the API call.

        Returns:
            A TokenUsage record with detailed usage and cost information.
        Raises:
            No exceptions are raised. Invalid responses are handled gracefully
            with zero token counts and appropriate warnings logged.
        Example:
            >>> tracker = TokenTracker()
            >>> record = tracker.record_from_openai_response(api_response, "gpt-4")
            >>> print(f"Cost: ${record.cost_usd:.4f}")
        """
        i, o, cr, request_id = _extract_usage_openai_like(resp)

        pricing: ModelPricing = get_pricing_for_model(
            model, pricing_map=self._pricing_map, warn=True
        )
        cost = compute_cost_usd(
            pricing,
            input_tokens=i,
            output_tokens=o,
            cache_input_tokens=cr,
        )

        record = TokenUsage(
            model=model,
            request_id=request_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            input_tokens=i,
            output_tokens=o,
            cache_input_tokens=cr,
            cost_usd=round(cost, 10),
        )

        # Update totals
        self._update_totals(record)

        # Log a concise line
        logger.info(
            "Token usage | model=%s id=%s in=%d out=%d cache_input=%d cost=$%.6f",
            model,
            request_id or "-",
            i,
            o,
            cr,
            record.cost_usd,
        )

        # Append to JSONL if configured
        if self._jsonl_path:
            try:
                line = json.dumps(asdict(record), ensure_ascii=False)
                with open(self._jsonl_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception as e:
                logger.warning("Failed to append token usage JSONL: %s", e)
        return record

    def totals(self) -> Dict[str, Any]:
        """Get aggregated totals of token usage and costs.
        Returns:
            A Dictionary with keys:
                - calls: Total number of API calls recorded.
                - input_tokens: Cumulative input tokens.
                - output_tokens: Cumulative output tokens.
                - cache_input_tokens: Cumulative cache input tokens.
                - cost_usd: Cumulative cost in USD, rounded to 10 decimal places.
        """
        return {
            "calls": self.call_count,
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "cache_input_tokens": self.total_cache_input_tokens,
            "cost_usd": round(self.total_cost_usd, 10),
        }
