from .base import ModelProvider
from .litellm_provider import LiteLLMProvider
from .openai_provider import OpenAIProvider


def _is_openai_model(model: str) -> bool:
    """Return True if *model* should be routed to the native OpenAI provider."""
    model_lower = model.lower()
    return any(
        p in model_lower
        for p in ["gpt", "o1", "o3", "o4", "davinci", "curie", "babbage", "ada"]
    )


def get_model_provider(model: str = None) -> ModelProvider:
    """Return the appropriate provider for *model*.

    OpenAI models use the native OpenAI Responses API provider.
    All other models (Anthropic, Gemini, etc.) go through LiteLLM.
    """
    if _is_openai_model(model):
        return OpenAIProvider()
    return LiteLLMProvider()
