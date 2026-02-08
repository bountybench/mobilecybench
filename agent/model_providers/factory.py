from .base import ModelProvider
from .litellm_provider import LiteLLMProvider
from .openai_responses_provider import OpenAIResponsesProvider


def _is_openai_model(model: str) -> bool:
    """Check if the model should use the OpenAI Responses API."""
    if not model:
        return False

    model_lower = model.lower()

    # Explicit responses prefix
    if model_lower.startswith("openai/responses/"):
        return True

    # Check for OpenAI model patterns
    openai_patterns = ["gpt", "o1", "o3", "o4", "davinci", "curie", "babbage", "ada", "codex"]
    return any(p in model_lower for p in openai_patterns)


def get_model_provider(model: str = None) -> ModelProvider:
    """Return the appropriate provider based on model.

    For OpenAI models: Returns OpenAIResponsesProvider (uses Responses API)
    For other models: Returns LiteLLMProvider (uses Chat Completions API)
    """
    if _is_openai_model(model):
        return OpenAIResponsesProvider()

    return LiteLLMProvider()
