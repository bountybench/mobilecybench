from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

from utils.logger import logger

from ..base import PricingCalculator, UsageExtractor
from ..constants import (
    ANTHROPIC_MODEL_MAPPINGS,
    CACHE_HITS_AND_REFRESHES_PRICE_FIELD,
    CACHE_INPUT_PRICE_FIELD,
    CACHE_WRITE_PRICE_FIELD,
    INPUT_PRICE_FIELD,
    OUTPUT_PRICE_FIELD,
    PROVIDER_ANTHROPIC,
    PROVIDER_OPENAI,
    REASONING_PRICE_FIELD,
)
from ..exceptions import (
    CalculatorNotConfiguredError,
    ExtractorNotConfiguredError,
    ModelPricingNotFoundError,
)
from ..models import ProviderPricing, UsageMetrics
from ..utils import strip_date_suffix
from .anthropic import AnthropicPricingCalculator, AnthropicUsageExtractor
from .openai import OpenAIPricingCalculator, OpenAIUsageExtractor


class ProviderPricingManager:
    def __init__(self, pricing_config_path: str):
        self.pricing_config = self.__load_pricing_config(pricing_config_path)
        self.extractors: Dict[str, UsageExtractor] = {
            PROVIDER_OPENAI: OpenAIUsageExtractor(),
            PROVIDER_ANTHROPIC: AnthropicUsageExtractor(),
            # TODO: other providers
        }
        self.calculators: Dict[str, PricingCalculator] = {
            PROVIDER_OPENAI: OpenAIPricingCalculator(),
            PROVIDER_ANTHROPIC: AnthropicPricingCalculator(),
            # TODO: other providers
        }

    # Public Methods
    def extract_usage_and_cost(
        self, response: Any, model: str, provider: str
    ) -> Tuple[UsageMetrics, float]:
        extractor = self.extractors.get(provider)
        if extractor is None:
            raise ExtractorNotConfiguredError(
                f"No usage extractor configured for provider '{provider}'"
            )

        usage = extractor.extract_usage(response)  # can raise UsageNotFoundError

        try:
            calculator = self.calculators.get(provider)
            if calculator is None:
                raise CalculatorNotConfiguredError(
                    f"No pricing calculator configured for provider '{provider}'"
                )
            pricing = self.__get_pricing(model, provider)
            cost = calculator.calculate_cost(usage, pricing)

        # failure in pricing or calculation is non-critical - continue token tracking
        except (ModelPricingNotFoundError, CalculatorNotConfiguredError) as e:
            logger.warning(f"Pricing calculation failed: {e}. Using $0.00 cost")
            cost = 0.0
        except Exception as e:
            logger.warning(
                f"Unexpected error in cost calculation: {e}. Using $0.00 cost"
            )
            cost = 0.0

        return usage, cost

    # Helper Methods
    def __load_pricing_config(self, path: str) -> Dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, IOError, json.JSONDecodeError) as e:
            logger.warning(
                f"Failed to load pricing config from {path}: {e}. Using $0.00 for all costs"
            )
            return {}

    def __get_pricing(self, model: str, provider: str) -> ProviderPricing:
        provider_models_pricing = self.pricing_config.get(provider, {})
        model_pricing = self.__resolve_model_pricing(
            model, provider, provider_models_pricing
        )
        return self.__build_pricing_for_provider(provider, model_pricing)

    def __resolve_model_pricing(
        self, model: str, provider: str, models: Dict[str, Any]
    ) -> Dict[str, Any]:
        if model in models:
            return models[model]

        # try to resolve model by stripping date suffix or using mappings
        if provider == PROVIDER_ANTHROPIC:
            resolved = self.__resolve_anthropic_model(model, models)
        elif provider == PROVIDER_OPENAI:
            resolved = self.__resolve_openai_model(model, models)
        # TODO: other providers
        else:
            # should never be reached due to earlier validation
            raise AssertionError(
                f"Unexpected provider '{provider}' - validation should have caught this"
            )

        if resolved:
            return resolved
        raise ModelPricingNotFoundError(
            f"No pricing found for model '{model}' from provider '{provider}'"
        )

    def __resolve_openai_model(
        self, model: str, models: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        base_model = strip_date_suffix(model)
        if base_model != model and base_model in models:
            logger.debug(f"Using pricing for '{base_model}' for model '{model}'")
            return models[base_model]
        return None

    def __resolve_anthropic_model(
        self, model: str, models: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        # Check explicit mappings
        if model in ANTHROPIC_MODEL_MAPPINGS:
            canonical_name = ANTHROPIC_MODEL_MAPPINGS[model]
            if canonical_name in models:
                logger.debug(
                    f"Using pricing for '{canonical_name}' for model '{model}'"
                )
                return models[canonical_name]

        # Try stripping date suffix
        base_model = strip_date_suffix(model)
        if base_model != model and base_model in models:
            logger.debug(f"Using pricing for '{base_model}' for model '{model}'")
            return models[base_model]

        return None

    def __build_pricing_for_provider(
        self, provider: str, model_pricing: Dict[str, Any]
    ) -> ProviderPricing:
        if provider == PROVIDER_OPENAI:
            return self.__build_openai_pricing(model_pricing)
        elif provider == PROVIDER_ANTHROPIC:
            return self.__build_anthropic_pricing(model_pricing)
        # TODO: other providers

        # should never be reached due to earlier validation
        raise AssertionError(
            f"Unexpected provider '{provider}' - validation should have caught this"
        )

    def __build_openai_pricing(self, model_pricing: Dict[str, Any]) -> ProviderPricing:
        return ProviderPricing(
            input_price=float(model_pricing.get(INPUT_PRICE_FIELD, 0) or 0),
            output_price=float(model_pricing.get(OUTPUT_PRICE_FIELD, 0) or 0),
            cache_price=float(model_pricing.get(CACHE_INPUT_PRICE_FIELD, 0) or 0),
            reasoning_price=float(model_pricing.get(REASONING_PRICE_FIELD, 0) or 0),
        )

    def __build_anthropic_pricing(
        self, model_pricing: Dict[str, Any]
    ) -> ProviderPricing:
        # TODO: Anthropic CacheCreation - 1h or 5min price selection logic.
        return ProviderPricing(
            input_price=float(model_pricing.get(INPUT_PRICE_FIELD, 0) or 0),
            output_price=float(model_pricing.get(OUTPUT_PRICE_FIELD, 0) or 0),
            cache_hits_and_refreshes_price=float(
                model_pricing.get(CACHE_HITS_AND_REFRESHES_PRICE_FIELD, 0) or 0
            ),
            cache_write_price=float(model_pricing.get(CACHE_WRITE_PRICE_FIELD, 0) or 0),
            reasoning_price=float(model_pricing.get(REASONING_PRICE_FIELD, 0) or 0),
        )
