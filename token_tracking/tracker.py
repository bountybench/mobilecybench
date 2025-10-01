from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, Optional

from utils.logger import logger

from .constants import COST_PRECISION, SUPPORTED_PROVIDERS
from .exceptions import UnsupportedProviderError
from .models import TokenUsage, UsageMetrics
from .providers import ProviderPricingManager


class TokenTracker:
    def __init__(
        self,
        *,
        pricing_path: Optional[str] = None,
        jsonl_path: Optional[str] = "token_usage.jsonl",
    ) -> None:
        if pricing_path is None:
            pricing_path = os.path.join(
                os.path.dirname(__file__), "data", "pricing.json"
            )

        self._pricing_manager = ProviderPricingManager(pricing_path)
        self._jsonl_path = jsonl_path

        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cache_tokens = 0
        self.total_cache_write_tokens = 0
        self.total_cost_usd = 0.0
        self.call_count = 0

    # Public API
    def record_from_response(self, resp: Any, model: str, provider: str) -> TokenUsage:
        model = model.strip()
        provider = provider.strip()
        if provider not in SUPPORTED_PROVIDERS:
            raise UnsupportedProviderError(
                f"Unsupported provider '{provider}'. Supported providers: {SUPPORTED_PROVIDERS}"
            )

        usage_metrics, cost = self._pricing_manager.extract_usage_and_cost(
            resp, model, provider
        )
        token_info_with_cost = self.__build_token_usage(
            model=model, usage_metrics=usage_metrics, cost=cost
        )
        self.__update_totals(token_info_with_cost)
        self.__append_usage_jsonl(token_info_with_cost)
        logger.info(
            "Token usage | model=%s id=%s in=%d out=%d cache=%d cache_write=%d cost=$%.6f",
            model,
            usage_metrics.request_id or "-",
            usage_metrics.input_tokens,
            usage_metrics.output_tokens,
            usage_metrics.cache_tokens,
            usage_metrics.cache_write_tokens,
            token_info_with_cost.cost_usd,
        )
        return token_info_with_cost

    def cumulative_tokens_info(self) -> Dict[str, Any]:
        """Get cumulative Token Usage and Cost info.

        - `calls`: Total number of API calls made
        - `input_tokens`: Total number of input tokens processed
        - `output_tokens`: Total number of output tokens generated
        - `cache_tokens`: Total number of tokens retrieved from cache
        - `cache_write_tokens`: Total number of tokens written to cache
        - `cost_usd`: Total cost in USD
        """
        return {
            "calls": self.call_count,
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "cache_tokens": self.total_cache_tokens,
            "cache_write_tokens": self.total_cache_write_tokens,
            "cost_usd": round(self.total_cost_usd, COST_PRECISION),
        }

    # Private Helpers
    def __update_totals(self, record: TokenUsage) -> None:
        self.total_input_tokens += record.input_tokens
        self.total_output_tokens += record.output_tokens
        self.total_cache_tokens += record.cache_tokens
        self.total_cache_write_tokens += record.cache_write_tokens
        self.total_cost_usd += record.cost_usd
        self.call_count += 1

    def __append_usage_jsonl(self, record: TokenUsage) -> None:
        if not self._jsonl_path:
            return
        try:
            line = json.dumps(asdict(record), ensure_ascii=False)
            with open(self._jsonl_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except (OSError, IOError, json.JSONEncodeError) as e:
            logger.warning("Failed to append token usage JSONL: %s", e)

    def __build_token_usage(
        self,
        *,
        model: str,
        usage_metrics: UsageMetrics,
        cost: float,
    ) -> TokenUsage:
        return TokenUsage(
            model=model,
            request_id=usage_metrics.request_id,
            created_at=datetime.now().isoformat(),
            input_tokens=usage_metrics.input_tokens,
            output_tokens=usage_metrics.output_tokens,
            cache_tokens=usage_metrics.cache_tokens,
            cache_write_tokens=usage_metrics.cache_write_tokens,
            cost_usd=round(cost, COST_PRECISION),
        )
