"""
Provider-agnostic pricing and usage extraction.

This module defines abstractions and implementations for extracting token usage
from LLM API responses (e.g., OpenAI, Anthropic) and calculating costs
based on provider-specific pricing structures.

Currently supported providers:
- OpenAI
- Anthropic
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional, Tuple

from utils.logger import logger


class UsageExtractor(ABC):
    """Abstract base for extracting usage from provider responses."""
    
    @abstractmethod
    def extract_usage(self, response: Any) -> UsageMetrics:
        """Extract usage metrics from provider response."""
        pass


class PricingCalculator(ABC):
    """Abstract base for calculating costs from usage."""
    
    @abstractmethod
    def calculate_cost(self, usage: UsageMetrics, pricing: ProviderPricing) -> float:
        """Calculate cost in USD from usage metrics and pricing."""
        pass


@dataclass(frozen=True)
class UsageMetrics:
    """Normalized usage metrics across providers."""
    
    input_tokens: int = 0
    output_tokens: int = 0
    cache_tokens: int = 0                       # Tokens served from cache (if supported)
    cache_write_tokens: int = 0                 # Cache write tokens (Anthropic style)
    reasoning_tokens: int = 0                   # Reasoning tokens (if supported)
    request_id: Optional[str] = None


@dataclass(frozen=True)
class ProviderPricing:
    """Provider-specific pricing structure."""
    
    input_price: float = 0.0
    output_price: float = 0.0
    
    # Optional pricing tiers
    cache_price: float = 0.0                            # Cache read pricing (OpenAI style)
    cache_hits_and_refreshes_price: float = 0.0         # Cache read pricing (Anthropic style)
    cache_write_price: float = 0.0                      # Cache write pricing (Anthropic style)
    reasoning_price: float = 0.0                        # Reasoning token pricing


class OpenAIUsageExtractor(UsageExtractor):
    """Extract usage from OpenAI API responses."""
    
    def extract_usage(self, response: Any) -> UsageMetrics:
        """Extract usage from OpenAI response format.

        # https://github.com/openai/openai-python/blob/main/src/openai/types/responses/response_usage.py
        """
        usage = getattr(response, "usage", None)
        if usage is None:
            logger.warning("No usage data found in OpenAI response")
            return UsageMetrics()

        return UsageMetrics(
            input_tokens=self._extract_core_tokens(usage, "input_tokens"),
            output_tokens=self._extract_core_tokens(usage, "output_tokens"),
            cache_tokens=self._extract_cache_tokens(usage),
            reasoning_tokens=self._extract_reasoning_tokens(usage),
            request_id=self._extract_request_id(response),
        )
    
    def _extract_request_id(self, response: Any) -> Optional[str]:
        req_id = getattr(response, "id", None)
        return str(req_id) if req_id is not None else None

    def _extract_core_tokens(self, usage: Any, field: str) -> int:
        try:
            if hasattr(usage, field):
                val = getattr(usage, field)
                return max(int(val or 0), 0)
        except (ValueError, TypeError):
            pass
        return 0
    
    def _extract_cache_tokens(self, usage: Any) -> int:
        input_details = getattr(usage, "input_tokens_details", None)
        if input_details and hasattr(input_details, "cached_tokens"):
            try:
                return max(int(getattr(input_details, "cached_tokens", 0) or 0), 0)
            except (ValueError, TypeError):
                pass
        return 0
    
    def _extract_reasoning_tokens(self, usage: Any) -> int:
        output_details = getattr(usage, "output_tokens_details", None)
        if output_details and hasattr(output_details, "reasoning_tokens"):
            try:
                return max(int(getattr(output_details, "reasoning_tokens", 0) or 0), 0)
            except (ValueError, TypeError):
                pass
        return 0


class AnthropicUsageExtractor(UsageExtractor):
    """Extract usage from Anthropic API responses.
    """
    
    def extract_usage(self, response: Any) -> UsageMetrics:
        """Extract usage from Anthropic response format.
        
        Reference - https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/types/usage.py
        Example Anthropic format:
        {
            "id": "msg_123",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_creation_input_tokens": 10,  # Optional
                "cache_read_input_tokens": 5        # Optional
            }
        }
        """
        usage = getattr(response, "usage", None)
        if usage is None:
            logger.warning("No usage data found in Anthropic response")
            return UsageMetrics()

        return UsageMetrics(
            input_tokens=self._extract_core_tokens(usage, "input_tokens"),
            output_tokens=self._extract_core_tokens(usage, "output_tokens"),
            cache_tokens=self._extract_cache_read_tokens(usage),
            cache_write_tokens=self._extract_cache_write_tokens(usage),
            reasoning_tokens=0,  # Anthropic doesn't expose reasoning tokens separately
            request_id=self._extract_request_id(response),
        )
        
    
    def _extract_request_id(self, response: Any) -> Optional[str]:
        req_id = getattr(response, "id", None)
        return str(req_id) if req_id is not None else None

    def _extract_core_tokens(self, usage: Any, field: str) -> int:
        """Extract basic input/output token counts."""
        try:
            if hasattr(usage, field):
                val = getattr(usage, field)
                return max(int(val or 0), 0)
        except (ValueError, TypeError):
            pass
        return 0
    
    def _extract_cache_read_tokens(self, usage: Any) -> int:
        """Extract cache read tokens (cache hits and refreshes)."""
        try:
            if hasattr(usage, "cache_read_input_tokens"):
                val = getattr(usage, "cache_read_input_tokens")
                return max(int(val or 0), 0)
        except (ValueError, TypeError):
            pass
        return 0
    
    def _extract_cache_write_tokens(self, usage: Any) -> int:
        """Extract cache write tokens (cache creation)."""
        try:
            if hasattr(usage, "cache_creation_input_tokens"):
                val = getattr(usage, "cache_creation_input_tokens")
                return max(int(val or 0), 0)
        except (ValueError, TypeError):
            pass
        return 0


class OpenAIPricingCalculator(PricingCalculator):
    """OpenAI-specific cost calculation."""
    
    def calculate_cost(self, usage: UsageMetrics, pricing: ProviderPricing) -> float:
        """Calculate cost using OpenAI's pricing model."""
        scale = 1_000_000.0
        
        # For OpenAI: billed input = total input - cached input
        billed_input = max(usage.input_tokens - usage.cache_tokens, 0)
        
        cost_input = (billed_input / scale) * pricing.input_price
        cost_output = (usage.output_tokens / scale) * pricing.output_price
        cost_cache = (usage.cache_tokens / scale) * pricing.cache_price
        cost_reasoning = (usage.reasoning_tokens / scale) * pricing.reasoning_price
        
        return float(cost_input + cost_output + cost_cache + cost_reasoning)


class AnthropicPricingCalculator(PricingCalculator):
    """Anthropic-specific cost calculation."""
    
    def calculate_cost(self, usage: UsageMetrics, pricing: ProviderPricing) -> float:
        """Calculate cost using Anthropic's pricing model."""
        scale = 1_000_000.0
        
        # Anthropic bills all input tokens (no cache deduction from input)
        cost_input = (usage.input_tokens / scale) * pricing.input_price
        cost_output = (usage.output_tokens / scale) * pricing.output_price
        
        # Anthropic cache pricing
        cost_cache_read = (usage.cache_tokens / scale) * pricing.cache_hits_and_refreshes_price
        cost_cache_write = (usage.cache_write_tokens / scale) * pricing.cache_write_price
        
        return float(cost_input + cost_output + cost_cache_read + cost_cache_write)


def _strip_date_suffix(model: str) -> str:
    """Strip date suffix from model name if present.
    
    Handles multiple date formats:
    - -YYYY-MM-DD (OpenAI style: gpt-4-2025-01-15)
    - -YYYYMMDD (Anthropic style: claude-sonnet-4-20250514)
    """
    # Try OpenAI format first: -YYYY-MM-DD
    openai_pattern = r"-\d{4}-\d{2}-\d{2}$"
    result = re.sub(openai_pattern, "", model)
    if result != model:
        return result
    
    # Try Anthropic format: -YYYYMMDD  
    anthropic_pattern = r"-\d{8}$"
    result = re.sub(anthropic_pattern, "", model)
    return result


class ProviderPricingManager:
    """Manages pricing for multiple providers."""
    
    def __init__(self, pricing_config_path: Optional[str] = None):
        self.pricing_config = self._load_pricing_config(pricing_config_path)
        
        self.extractors = {
            "openai": OpenAIUsageExtractor(),
            "anthropic": AnthropicUsageExtractor(),
        }
        
        self.calculators = {
            "openai": OpenAIPricingCalculator(),
            "anthropic": AnthropicPricingCalculator(),
        }
    
    def _load_pricing_config(self, path: Optional[str] = None) -> Dict[str, Any]:
        """Load provider pricing configuration."""
        if path is None:
            # Use the existing token_pricing.json file
            import os
            path = os.path.join(os.path.dirname(__file__), "token_pricing.json")
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load pricing config {path}: {e}")
            return {}
    
    def get_provider_from_model(self, model: str) -> str:
        """Determine provider from model name."""
        # Common model prefixes and names
        if model.startswith(("gpt-", "o1-", "chatgpt-")) or model in ("o3",):
            return "openai"
        elif model.startswith(("claude-", "sonnet-", "haiku-", "opus-")):
            return "anthropic"
        else:
            raise ValueError(f"Unknown model '{model}' - cannot determine provider. Supported providers: openai, anthropic")
    
    def get_pricing(self, model: str, provider: Optional[str] = None) -> ProviderPricing:
        """Get pricing for a model, with fallback logic."""
        if provider is None:
            provider = self.get_provider_from_model(model)
        
        provider_config = self.pricing_config.get(provider, {})
        # Direct model pricing (current structure in token_pricing.json)
        models = provider_config
        
        # Try exact model match first
        if model in models:
            model_pricing = models[model]
        else:
            # Try with date suffix stripped
            base_model = _strip_date_suffix(model)
            if base_model != model and base_model in models:
                logger.debug(f"Using pricing for '{base_model}' for model '{model}'")
                model_pricing = models[base_model]
            else:
                # Try Anthropic model name variations
                model_pricing = self._find_anthropic_model_pricing(base_model, models, provider)
                if model_pricing is None:
                    logger.warning(f"No pricing found for model '{model}', using zeros")
                    model_pricing = {}
                else:
                    logger.debug(f"Found Anthropic model variation for '{model}'")
        
        # Provider-specific pricing fields
        if provider == "anthropic":
            return ProviderPricing(
                input_price=float(model_pricing.get("input", 0) or 0),
                output_price=float(model_pricing.get("output", 0) or 0),
                cache_hits_and_refreshes_price=float(model_pricing.get("cache_hits_and_refreshes", 0) or 0),
                cache_write_price=float(model_pricing.get("cache_write", 0) or 0),
                reasoning_price=float(model_pricing.get("reasoning", 0) or 0),
            )
        elif provider == "openai":
            return ProviderPricing(
                input_price=float(model_pricing.get("input", 0) or 0),
                output_price=float(model_pricing.get("output", 0) or 0),
                cache_price=float(model_pricing.get("cache_input", 0) or 0),
                reasoning_price=float(model_pricing.get("reasoning", 0) or 0),
            )
        else:
            raise ValueError(f"Unsupported provider '{provider}' for pricing calculation")
    
    def _find_anthropic_model_pricing(self, base_model: str, models: dict, provider: str) -> Optional[dict]:
        """Find pricing for Anthropic model variations."""
        if provider != "anthropic":
            return None
            
        # Common Anthropic model mappings
        anthropic_mappings = {
            "claude-sonnet-4": "claude-sonnet-4-0",
            "claude-opus-4": "claude-opus-4-0", 
            "claude-3-7-sonnet": "claude-3-7-sonnet-latest",
        }
        
        # Check if we have a mapping for this base model
        mapped_model = anthropic_mappings.get(base_model)
        if mapped_model and mapped_model in models:
            return models[mapped_model]
            
        return None
    
    def extract_usage_and_cost(
        self, 
        response: Any, 
        model: str, 
        provider: Optional[str] = None
    ) -> Tuple[UsageMetrics, float]:
        """Extract usage and calculate cost for any provider."""
        if provider is None:
            provider = self.get_provider_from_model(model)
        
        # Extract usage metrics
        extractor = self.extractors.get(provider)
        if extractor is None:
            raise ValueError(f"No extractor available for provider '{provider}'")
        
        usage = extractor.extract_usage(response)
        
        # Get pricing and calculate cost
        pricing = self.get_pricing(model, provider)
        
        calculator = self.calculators.get(provider)
        if calculator is None:
            raise ValueError(f"No calculator available for provider '{provider}'")
        
        cost = calculator.calculate_cost(usage, pricing)
        
        return usage, cost

"""
  Anthropic model variations supported:
    1. claude-3-7-sonnet-latest → Direct match
    2. claude-3-7-sonnet-20250219 → Maps to claude-3-7-sonnet-latest
    3. claude-sonnet-4-20250514 → Maps to claude-sonnet-4-0
    4. claude-sonnet-4-0 → Direct match
    5. claude-opus-4-0 → Direct match
    6. claude-opus-4-20250514 → Maps to claude-opus-4-0
"""
