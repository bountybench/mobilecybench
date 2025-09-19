"""Deprecated module - Use pricing_providers.py instead.

This module is kept only for the ModelPricing dataclass which may be used 
for backward compatibility in some interfaces.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPricing:
    """Legacy pricing structure - use ProviderPricing instead.
    
    Per-1M token pricing for a model.
    All values are USD per 1,000,000 tokens.
    
    Note: This is kept for backward compatibility only.
    New code should use pricing_providers.ProviderPricing.
    """

    input: float = 0.0
    output: float = 0.0
    cache_input: float = 0.0  # OpenAI style
    cache_hits_and_refreshes: float = 0.0  # Anthropic style  
    cache_write: float = 0.0  # Anthropic style