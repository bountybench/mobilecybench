from __future__ import annotations

from typing import Literal

from .base import ModelProvider
from .openai_provider import OpenAIProvider
from .gemini_provider import GeminiProvider
from .anthropic_provider import AnthropicProvider

# TODO: update the list as new providers are added
ProviderName = Literal["openai", "gemini", "anthropic"]


def get_model_provider(name: ProviderName | None = None) -> ModelProvider:
    """Return a model provider instance based on name.

    - "openai" (default)
    - "gemini"
    - "anthropic"
    """
    provider_name = (name or "openai").lower()

    if provider_name == "openai":
        return OpenAIProvider()
    elif provider_name == "gemini":
        return GeminiProvider()
    elif provider_name == "anthropic":
        return AnthropicProvider()

    raise ValueError(f"Unsupported MODEL_PROVIDER: {provider_name}")
