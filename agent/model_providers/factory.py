from .base import ModelProvider
from .openai_provider import OpenAIProvider


def get_model_provider(model: str = None) -> ModelProvider:
    return OpenAIProvider()     # currently only one provider
