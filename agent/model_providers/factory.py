from typing import Any, Dict, List, Optional

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


def get_model_provider(
    model: str,
    instructions: str,
    tools: Optional[List[Dict]] = None,
    max_output_tokens: Optional[int] = None,
    timeout_ms: Optional[int] = None,
    reasoning_effort: Optional[str] = None,
) -> ModelProvider:
    """Return a fully configured provider for *model*.

    OpenAI models use the native OpenAI Responses API provider.
    All other models (Anthropic, Gemini, etc.) go through LiteLLM.
    """
    kwargs: Dict[str, Any] = dict(
        model=model,
        instructions=instructions,
        tools=tools,
        max_output_tokens=max_output_tokens,
        timeout_ms=timeout_ms,
        reasoning_effort=reasoning_effort,
    )
    if _is_openai_model(model):
        return OpenAIProvider(**kwargs)
    return LiteLLMProvider(**kwargs)
