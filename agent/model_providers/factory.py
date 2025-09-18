from __future__ import annotations

from typing import Literal

from .base import ModelProvider
from .openai_provider import OpenAIProvider

# TODO: update the list as new providers are added
ProviderName = Literal["openai"]


def get_model_provider(name: ProviderName | None = None) -> ModelProvider:
    """Return a model provider instance based on name.

    - "openai" (default)
    """
    provider_name = (name or "openai").lower()

    if provider_name == "openai":
        return OpenAIProvider()

    # TODO: add other providers here as elif branches

    raise ValueError(f"Unsupported MODEL_PROVIDER: {provider_name}")
