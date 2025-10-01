# Anthropic Response Usage Reference:
# https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/types/usage.py

from __future__ import annotations

from typing import Any, Optional

from utils.logger import logger

from ..base import PricingCalculator, UsageExtractor
from ..constants import TOKENS_PER_MILLION
from ..exceptions import UsageNotFoundError
from ..models import ProviderPricing, UsageMetrics


class AnthropicUsageExtractor(UsageExtractor):
    def extract_usage(self, response: Any) -> UsageMetrics:
        usage = getattr(response, "usage", None)
        if usage is None:
            raise UsageNotFoundError("No usage data found in Anthropic response")

        return UsageMetrics(
            input_tokens=self.__extract_core_tokens(usage, "input_tokens"),
            output_tokens=self.__extract_core_tokens(usage, "output_tokens"),
            cache_tokens=self.__extract_cache_read_tokens(usage),
            cache_write_tokens=self.__extract_cache_write_tokens(usage),
            reasoning_tokens=0,  # Anthropic response does not have reasoning tokens field
            request_id=self.__extract_request_id(response),
        )

    # Private Helpers
    def __extract_request_id(self, response: Any) -> Optional[str]:
        req_id = getattr(response, "id", None)
        return str(req_id) if req_id is not None else None

    def __extract_core_tokens(self, usage: Any, field: str) -> int:
        try:
            val = getattr(usage, field, 0)
            return max(int(val or 0), 0)
        except (ValueError, TypeError, AttributeError):
            logger.warning(
                f"Error extracting {field} from Anthropic usage. Defaulting to 0."
            )
            return 0

    def __extract_cache_read_tokens(self, usage: Any) -> int:
        # TODO: Anthropic CacheCreation - 1h, 5min price selection logic.
        try:
            val = getattr(usage, "cache_read_input_tokens", 0)
            return max(int(val or 0), 0)
        except (ValueError, TypeError, AttributeError):
            logger.warning(
                "Error extracting cache read tokens from Anthropic usage. Defaulting to 0."
            )
            return 0

    def __extract_cache_write_tokens(self, usage: Any) -> int:
        try:
            val = getattr(usage, "cache_creation_input_tokens", 0)
            return max(int(val or 0), 0)
        except (ValueError, TypeError, AttributeError):
            logger.warning(
                "Error extracting cache write tokens from Anthropic usage. Defaulting to 0."
            )
            return 0


class AnthropicPricingCalculator(PricingCalculator):
    def calculate_cost(self, usage: UsageMetrics, pricing: ProviderPricing) -> float:
        scale = TOKENS_PER_MILLION

        # Anthropic bills all input tokens (no cache deduction from input)
        cost_input = (usage.input_tokens / scale) * pricing.input_price
        cost_output = (usage.output_tokens / scale) * pricing.output_price
        cost_cache_read = (
            usage.cache_tokens / scale
        ) * pricing.cache_hits_and_refreshes_price
        cost_cache_write = (
            usage.cache_write_tokens / scale
        ) * pricing.cache_write_price

        return float(cost_input + cost_output + cost_cache_read + cost_cache_write)
