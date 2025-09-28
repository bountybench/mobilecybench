from __future__ import annotations

from typing import Literal

from .base import ModelProvider
from .openai_provider import OpenAIProvider
from .claude_provider import ClaudeProvider
from .gemini_provider import GeminiProvider

# Updated list with new providers
ProviderName = Literal["openai", "claude", "gemini"]


def get_model_provider(name: ProviderName | None = None) -> ModelProvider:
    """Return a model provider instance based on name.

    - "openai" (default)
    - "claude" (Anthropic Claude)
    - "gemini" (Google Gemini)
    """
    provider_name = (name or "openai").lower()

    if provider_name == "openai":
        return OpenAIProvider()
    elif provider_name == "claude":
        return ClaudeProvider()
    elif provider_name == "gemini":
        return GeminiProvider()

    raise ValueError(f"Unsupported MODEL_PROVIDER: {provider_name}")
