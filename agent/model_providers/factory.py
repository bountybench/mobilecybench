from __future__ import annotations

from typing import Literal, Optional

from .base import ModelProvider
from .litellm_provider import LiteLLMProvider

# Provider name type - now primarily uses litellm
ProviderName = Literal["litellm", "openai", "gemini"]


def detect_provider_from_model(model: str) -> str:
    """Detect the appropriate provider based on model name.

    Note: This is now primarily used for API key validation.
    All models are routed through LiteLLM which handles the actual provider routing.

    Args:
        model: Model identifier (e.g., 'gpt-4', 'gemini-3-pro-preview')

    Returns:
        Provider name ('openai', 'gemini', or 'anthropic')
    """
    model_lower = model.lower()

    # Gemini models
    if any(
        prefix in model_lower
        for prefix in [
            "gemini",
            "gemma",
            "learnlm",
            "imagen",
        ]
    ):
        return "gemini"

    # Anthropic models
    if any(prefix in model_lower for prefix in ["claude", "anthropic"]):
        return "anthropic"

    # OpenAI models (including o1, o3 reasoning models)
    if any(
        prefix in model_lower
        for prefix in [
            "gpt",
            "o1",
            "o3",
            "davinci",
            "curie",
            "babbage",
            "ada",
        ]
    ):
        return "openai"

    # Default to OpenAI for unknown models
    return "openai"


def get_model_provider(
    name: Optional[ProviderName] = None, model: Optional[str] = None
) -> ModelProvider:
    """Return a model provider instance.

    This now returns a LiteLLM provider which provides a unified interface
    to all supported model providers (OpenAI, Gemini, Anthropic, etc.).

    Args:
        name: Explicit provider name (deprecated, ignored - always uses LiteLLM)
        model: Model identifier for validation purposes

    Returns:
        LiteLLMProvider instance
    """
    # Always use LiteLLM provider for unified model access
    # The model name determines which API key to validate and which
    # underlying provider LiteLLM will use
    return LiteLLMProvider()
