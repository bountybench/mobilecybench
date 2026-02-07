from .base import ModelProvider
from .litellm_provider import LiteLLMProvider


def get_model_provider(model: str = None) -> ModelProvider:
    """Return a LiteLLM provider instance for unified model access."""
    return LiteLLMProvider()
