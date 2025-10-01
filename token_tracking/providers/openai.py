# OpenAI Response Usage Reference:
# https://github.com/openai/openai-python/blob/main/src/openai/types/responses/response_usage.py

from __future__ import annotations

from typing import Any, Optional

from utils.logger import logger

from ..base import PricingCalculator, UsageExtractor
from ..constants import TOKENS_PER_MILLION
from ..exceptions import UsageNotFoundError
from ..models import ProviderPricing, UsageMetrics


class OpenAIUsageExtractor(UsageExtractor):
    def extract_usage(self, response: Any) -> UsageMetrics:
        usage = getattr(response, "usage", None)
        if usage is None:
            raise UsageNotFoundError("No usage data found in OpenAI response")

        return UsageMetrics(
            input_tokens=self.__extract_core_tokens(usage, "input_tokens"),
            output_tokens=self.__extract_core_tokens(usage, "output_tokens"),
            cache_tokens=self.__extract_cache_tokens(usage),
            reasoning_tokens=self.__extract_reasoning_tokens(usage),
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
                f"Error extracting {field} from OpenAI usage. Defaulting to 0."
            )
            return 0

    def __extract_cache_tokens(self, usage: Any) -> int:
        input_details = getattr(usage, "input_tokens_details", None)
        if input_details:
            try:
                val = getattr(input_details, "cached_tokens", 0)
                return max(int(val or 0), 0)
            except (ValueError, TypeError, AttributeError):
                logger.warning(
                    "Error extracting cached tokens from OpenAI usage details. Defaulting to 0."
                )
        return 0

    def __extract_reasoning_tokens(self, usage: Any) -> int:
        output_details = getattr(usage, "output_tokens_details", None)
        if output_details:
            try:
                val = getattr(output_details, "reasoning_tokens", 0)
                return max(int(val or 0), 0)
            except (ValueError, TypeError, AttributeError):
                logger.warning(
                    "Error extracting reasoning tokens from OpenAI usage details. Defaulting to 0."
                )
        return 0


class OpenAIPricingCalculator(PricingCalculator):
    def calculate_cost(self, usage: UsageMetrics, pricing: ProviderPricing) -> float:
        scale = TOKENS_PER_MILLION

        # OpenAI: billed input = total input - cached input
        billed_input = max(usage.input_tokens - usage.cache_tokens, 0)
        cost_input = (billed_input / scale) * pricing.input_price
        cost_output = (usage.output_tokens / scale) * pricing.output_price
        cost_cache = (usage.cache_tokens / scale) * pricing.cache_price
        cost_reasoning = (usage.reasoning_tokens / scale) * pricing.reasoning_price

        return float(cost_input + cost_output + cost_cache + cost_reasoning)
