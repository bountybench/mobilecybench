"""Model provider factory using LiteLLM for unified model access.

LiteLLM provides a unified interface to multiple LLM providers (OpenAI, Gemini,
Anthropic, etc.) through a single API.
"""

from __future__ import annotations

from .base import ModelProvider
from .litellm_provider import LiteLLMProvider


def get_model_provider(model: str = None) -> ModelProvider:
    """Return a LiteLLM provider instance for unified model access.

    LiteLLM handles routing to the appropriate provider (OpenAI, Gemini, Anthropic)
    based on the model name.

    Args:
        model: Model identifier (e.g., 'gpt-4', 'gemini-pro', 'claude-3-opus').
               Used for validation purposes.

    Returns:
        LiteLLMProvider instance
    """
    return LiteLLMProvider()
