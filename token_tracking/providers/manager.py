
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, Tuple

from ..base import PricingCalculator, UsageExtractor
from ..constants import (
    ANTHROPIC_MODEL_MAPPINGS,
    CACHE_HITS_AND_REFRESHES_PRICE_FIELD,
    CACHE_INPUT_PRICE_FIELD,
    CACHE_WRITE_PRICE_FIELD,
    INPUT_PRICE_FIELD,
    OUTPUT_PRICE_FIELD,
    REASONING_PRICE_FIELD,
    PROVIDER_ANTHROPIC,
    PROVIDER_OPENAI,
    SUPPORTED_PROVIDERS,
)
from ..models import ProviderPricing, UsageMetrics
from ..utils import logger, strip_date_suffix
from .anthropic import AnthropicPricingCalculator, AnthropicUsageExtractor
from .openai import OpenAIPricingCalculator, OpenAIUsageExtractor


class ModelPricingNotFoundError(Exception):
    """Raised when no pricing information is found for a given model.

    Continue with all prices set to $0.0. Token Count is still tracked.
    """
    pass

class UnsupportedProviderError(Exception):
    """Raised when an unsupported provider is specified.

    Bubble up to caller to handle. Entire token tracking should be skipped.
    """
    pass

class ProviderPricingManager:
    def __init__(self, pricing_config_path: Optional[str] = None):
        self.pricing_config = self.__load_pricing_config(pricing_config_path)
        self.extractors: Dict[str, UsageExtractor] = {
            PROVIDER_OPENAI: OpenAIUsageExtractor(),
            PROVIDER_ANTHROPIC: AnthropicUsageExtractor(),
        }
        self.calculators: Dict[str, PricingCalculator] = {
            PROVIDER_OPENAI: OpenAIPricingCalculator(),
            PROVIDER_ANTHROPIC: AnthropicPricingCalculator(),
        }

    # Public Methods
    def extract_usage_and_cost(
        self, response: Any, model: str, provider: str
    ) -> Tuple[UsageMetrics, float]:
        extractor = self.extractors.get(provider)
        if extractor is None:
            raise ValueError(f"No extractor available for provider '{provider}'."
                             f"Make sure extractor for {provider} is implemented and initialized properly.")
        usage = extractor.extract_usage(response)

        try:
            pricing = self.__get_pricing(model, provider)
        except UnsupportedProviderError as e:
            logger.warning(f"{e}. Bubbling up to caller to skip token tracking.")
            raise e

        calculator = self.calculators.get(provider)
        if calculator is None:
            raise ValueError(f"No calculator available for provider '{provider}'."
                             f"Make sure calculator for {provider} is implemented and initialized properly.")

        cost = calculator.calculate_cost(usage, pricing)
        return usage, cost

    
    # Helper Methods
    def __load_pricing_config(self, path: Optional[str] = None) -> Dict[str, Any]:
        if path is None:
            path = os.path.join(os.path.dirname(__file__), "..", "data", "pricing.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, IOError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to load pricing config {path}: {e}")
            logger.warning("Token cost calculations will result in $0.0 because of load_pricing_config failure.")
            return {}

    def __get_pricing(self, model: str, provider: str) -> ProviderPricing:
        if provider not in SUPPORTED_PROVIDERS:
            raise UnsupportedProviderError(
                f"Unsupported provider '{provider}' for pricing calculation. Currently supported: {SUPPORTED_PROVIDERS}"
            )
        provider_models_pricing = self.pricing_config.get(provider, {})
        try:
            model_pricing = self.__resolve_model_pricing(model, provider, provider_models_pricing)
        except ModelPricingNotFoundError as e:
            logger.warning(f"{e}. All token prices set to $0.0.")
            return ProviderPricing()
        
        return self.__build_pricing_for_provider(provider, model_pricing)

    def __resolve_model_pricing(
        self, model: str, provider: str, models: Dict[str, Any]
    ) -> Dict[str, Any]:
        # exact key match
        if model in models:
            return models[model]

        # try to resolve model by stripping date suffix or using mappings
        if provider == PROVIDER_ANTHROPIC:
            resolved = self.__resolve_anthropic_model(model, models)
        elif provider == PROVIDER_OPENAI:
            resolved = self.__resolve_openai_model(model, models)
        # TODO: other providers
        else: # should not reach here
            raise UnsupportedProviderError(
                f"Unsupported provider '{provider}'"
            )

        if resolved:
            return resolved
        raise ModelPricingNotFoundError(
            f"No pricing found for model '{model}' from provider '{provider}'."
            f"Attempted date suffix stripping and model mappings."
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
        else:  # should not reach here
            raise UnsupportedProviderError(
                f"Unsupported provider '{provider}'"
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
