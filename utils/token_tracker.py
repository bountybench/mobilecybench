"""Token usage tracking and cost calculation for API calls.

This module defines a TokenTracker class that can record token usage from
OpenAI-like response objects, compute costs based on a pricing map, and maintain
aggregated totals. It supports logging usage records to a JSONL file for detailed
analysis.

TODO: - Extend support for other API response formats. Currently only OpenAI-like responses are handled.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from utils.logger import logger
from utils.pricing_providers import ProviderPricingManager, UsageMetrics


@dataclass
class TokenUsage:
    """A normalized record of tokens and cost for a single API call.

    Attributes:
        - model: The model name used for the API call.
        - request_id: The unique request ID from the API response, if available.
        - created_at: timestamp when the record was created.
        - input_tokens: Number of input tokens used.
        - output_tokens: Number of output tokens generated.
        - cache_tokens: Number of input tokens served from cache.
        - cache_write_tokens: Number of cache write tokens (for Anthropic).
        - cost_usd: Total cost in USD for this call, rounded to 10 decimal places.
    """

    model: str
    request_id: Optional[str]
    created_at: str
    input_tokens: int
    output_tokens: int
    cache_tokens: int
    cache_write_tokens: int
    cost_usd: float




class TokenTracker:
    """Tracks and aggregates token usage and costs across multiple API calls.

    This class maintains running totals of token usage and costs.

    Attributes:
        - total_input_tokens: Cumulative input tokens across all recorded calls.
        - total_output_tokens: Cumulative output tokens across all recorded calls.
        - total_cache_tokens: Cumulative cache-read input tokens across all calls.
        - total_cache_write_tokens: Cumulative cache write tokens across all calls.
        - total_cost_usd: Cumulative cost in USD across all recorded calls.
        - call_count: Total number of API calls recorded.

    Example usage:
        >>> tracker = TokenTracker(pricing_path="custom_pricing.json")
        >>> record = tracker.record_from_response(api_response, "claude-sonnet-4-0")
        >>> print(tracker.totals())
        {'calls': 1, 'input_tokens': 1000, 'output_tokens': 500, ...}
    """

    def __init__(
        self,
        *,
        pricing_path: Optional[str] = None,
    ) -> None:
        """Initialize the TokenTracker.
        Args:
            - pricing_path: optional path to a JSON file with model pricing data.
                * If None, uses default location from pricing_providers module.
        """
        self._pricing_manager = ProviderPricingManager(pricing_path)
        self._jsonl_path = "token_usage.jsonl"

        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cache_tokens = 0
        self.total_cache_write_tokens = 0
        self.total_cost_usd = 0.0
        self.call_count = 0

    def _update_totals(self, record: TokenUsage) -> None:
        """Update running totals with data from a new usage record."""
        self.total_input_tokens += record.input_tokens
        self.total_output_tokens += record.output_tokens
        self.total_cache_tokens += record.cache_tokens
        self.total_cache_write_tokens += record.cache_write_tokens
        self.total_cost_usd += record.cost_usd
        self.call_count += 1

    def record_from_response(self, resp: Any, model: str, provider: str) -> TokenUsage:
        """Record token usage from any provider API response.

        Extracts token usage data from the response, calculates cost using
        provider-specific logic, updates running totals.

        Args:
            resp: The response object from an API call (OpenAI, Anthropic, etc.).
            model: The model name used for the API call.
            provider: The provider name (e.g., "openai", "anthropic").

        Returns:
            A TokenUsage record with detailed usage and cost information.
        Raises:
            No exceptions are raised. Invalid responses are handled gracefully
            with zero token counts and appropriate warnings logged.
        Example:
            >>> tracker = TokenTracker()
            >>> record = tracker.record_from_response(api_response, "claude-sonnet-4-0", "anthropic")
            >>> print(f"Cost: ${record.cost_usd:.4f}")
        """
        # Extract usage and calculate cost using provider-specific logic
        usage_metrics, cost = self._pricing_manager.extract_usage_and_cost(resp, model, provider)

        record = TokenUsage(
            model=model,
            request_id=usage_metrics.request_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            input_tokens=usage_metrics.input_tokens,
            output_tokens=usage_metrics.output_tokens,
            cache_tokens=usage_metrics.cache_tokens,
            cache_write_tokens=usage_metrics.cache_write_tokens,
            cost_usd=round(cost, 10),
        )

        # Update totals
        self._update_totals(record)

        # Log a concise line
        logger.info(
            "Token usage | model=%s id=%s in=%d out=%d cache=%d cache_write=%d cost=$%.6f",
            model,
            usage_metrics.request_id or "-",
            usage_metrics.input_tokens,
            usage_metrics.output_tokens,
            usage_metrics.cache_tokens,
            usage_metrics.cache_write_tokens,
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
                - cache_tokens: Cumulative cache input tokens.
                - cache_write_tokens: Cumulative cache write tokens.
                - cost_usd: Cumulative cost in USD, rounded to 10 decimal places.
        """
        return {
            "calls": self.call_count,
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "cache_tokens": self.total_cache_tokens,
            "cache_write_tokens": self.total_cache_write_tokens,
            "cost_usd": round(self.total_cost_usd, 10),
        }
