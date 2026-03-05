from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from .base import ModelProvider
from .litellm_provider import LiteLLMProvider
from .openai_provider import OpenAIProvider


@dataclass(frozen=True)
class ModelConfig:
    """Provider routing configuration for a model."""

    api_id: str  # Model ID string sent to the API
    provider: str  # "openai" (Responses API) or "litellm"


class SupportedModel(Enum):
    """Supported models and their provider routing.

    All entries use thinking-enabled variants by default:
    - GPT-5.2: thinking mode (not Instant/chat-latest)
    - Claude: extended thinking via thinking parameter
    - Gemini 3 Pro: thinking_level defaults to high
    """

    # OpenAI — native Responses API provider
    GPT_5_2 = ModelConfig("gpt-5.2", "openai")
    GPT_5_2_PRO = ModelConfig("gpt-5.2-pro", "openai")
    GPT_5_2_CODEX = ModelConfig("gpt-5.2-codex", "openai")

    # Anthropic — LiteLLM provider
    CLAUDE_OPUS_4_6 = ModelConfig("claude-opus-4-6", "litellm")
    CLAUDE_SONNET_4_5 = ModelConfig("claude-sonnet-4-5-20250929", "litellm")

    # Google — LiteLLM provider
    GEMINI_3_PRO = ModelConfig("gemini-3-pro-preview", "litellm")


# Lookup table: api_id → SupportedModel
_MODEL_REGISTRY: Dict[str, SupportedModel] = {m.value.api_id: m for m in SupportedModel}


def get_model_provider(
    model: str,
    instructions: str,
    tools: Optional[List[Dict]] = None,
    max_output_tokens: Optional[int] = None,
    timeout_ms: Optional[int] = None,
    reasoning_effort: Optional[str] = None,
) -> ModelProvider:
    """Return a fully configured provider for *model*.

    Looks up the model in the SupportedModel registry to determine
    which provider to use:
    - OpenAI models → native Responses API provider
    - Everything else → LiteLLM provider
    """
    entry = _MODEL_REGISTRY.get(model)
    if entry is None:
        supported = [m.value.api_id for m in SupportedModel]
        raise ValueError(
            f"Unsupported model: '{model}'. " f"Supported models: {supported}"
        )

    kwargs: Dict[str, Any] = dict(
        model=model,
        instructions=instructions,
        tools=tools,
        max_output_tokens=max_output_tokens,
        timeout_ms=timeout_ms,
        reasoning_effort=reasoning_effort,
    )

    if entry.value.provider == "openai":
        return OpenAIProvider(**kwargs)
    return LiteLLMProvider(**kwargs)
