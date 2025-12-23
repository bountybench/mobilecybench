from __future__ import annotations

from typing import Literal

from .base import ModelProvider
from .gemini_provider import GeminiProvider
from .openai_provider import OpenAIProvider

# TODO: update the list as new providers are added
ProviderName = Literal["openai", "gemini"]


def detect_provider_from_model(model: str) -> str:
    """Detect the appropriate provider based on model name.

    Args:
        model: Model identifier (e.g., 'gpt-4', 'gemini-3-pro-preview')

    Returns:
        Provider name ('openai' or 'gemini')
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

    # OpenAI models
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
    name: ProviderName | None = None, model: str | None = None
) -> ModelProvider:
    """Return a model provider instance based on name or model.

    Args:
        name: Explicit provider name ('openai', 'gemini')
        model: Model identifier to auto-detect provider from

    Returns:
        ModelProvider instance

    - "openai" (default)
    - "gemini" for Google Gemini models
    """
    # If explicit name provided, use it
    if name:
        provider_name = name.lower()
    # Otherwise detect from model
    elif model:
        provider_name = detect_provider_from_model(model)
    else:
        provider_name = "openai"  # default

    if provider_name == "openai":
        return OpenAIProvider()
    elif provider_name == "gemini":
        return GeminiProvider()

    # TODO: add other providers here as elif branches

    raise ValueError(f"Unsupported MODEL_PROVIDER: {provider_name}")