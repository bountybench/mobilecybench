from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class UsageMetrics:
    """Normalized usage metrics across providers.

    All tokens are defaulted to 0.
    """
    input_tokens: int = 0
    output_tokens: int = 0
    cache_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    request_id: Optional[str] = None


@dataclass(frozen=True)
class ProviderPricing:
    """Data class for provider pricing information.
    
    All prices are defaulted to 0.
    Note: 
        - cache_price is for OpenAI.
        - cache_hits_and_refreshes_price and cache_write_price are for Anthropic.
        - currently, cache_write_price (5 minutes) price is used.
    """

    input_price: float = 0.0
    output_price: float = 0.0

    cache_price: float = 0.0
    cache_hits_and_refreshes_price: float = 0.0
    cache_write_price: float = 0.0
    reasoning_price: float = 0.0


@dataclass
class TokenUsage:
    """A record of tokens and cost for a single API call."""

    model: str
    request_id: Optional[str]
    created_at: str
    input_tokens: int
    output_tokens: int
    cache_tokens: int
    cache_write_tokens: int
    cost_usd: float
