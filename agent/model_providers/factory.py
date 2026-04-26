from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from utils.logger import logger

from .base import ModelProvider
from .litellm_provider import LiteLLMProvider, _lookup_rule
from .openai_provider import OpenAIProvider


@dataclass(frozen=True)
class ModelConfig:
    """Provider routing configuration for a model."""

    api_id: str  # Model ID string sent to the API
    provider: str  # "openai" (Responses API) or "litellm"


class SupportedModel(Enum):
    """Supported models and their provider routing.

    To add a new model, add an entry here with the right provider tag:
    - ``"openai"`` → routed through the Responses API (``OpenAIProvider``).
    - ``"litellm"`` → routed through LiteLLM Chat Completions
      (``LiteLLMProvider``). Make sure the model name is recognized by
      LiteLLM, or register a detection rule via
      ``agent.model_providers.litellm_provider.register_provider``.

    See ``documentation/ADDING_MODELS.md`` for the full checklist.

    All entries use thinking-enabled variants by default:
    - GPT-5.x: thinking mode (not Instant/chat-latest)
    - Claude: extended thinking via thinking parameter
    - Gemini 3.x Pro: thinking_level defaults to high
    """

    # OpenAI — native Responses API provider
    # Newest first; older entries kept for backwards compatibility.
    GPT_5_5 = ModelConfig("gpt-5.5", "openai")
    GPT_5_5_PRO = ModelConfig("gpt-5.5-pro", "openai")
    GPT_5_4 = ModelConfig("gpt-5.4", "openai")
    GPT_5_4_PRO = ModelConfig("gpt-5.4-pro", "openai")
    GPT_5_2 = ModelConfig("gpt-5.2", "openai")
    GPT_5_2_PRO = ModelConfig("gpt-5.2-pro", "openai")
    GPT_5_2_CODEX = ModelConfig("gpt-5.2-codex", "openai")

    # Anthropic — LiteLLM provider
    CLAUDE_OPUS_4_7 = ModelConfig("claude-opus-4-7", "litellm")
    CLAUDE_SONNET_4_6 = ModelConfig("claude-sonnet-4-6", "litellm")
    CLAUDE_OPUS_4_6 = ModelConfig("claude-opus-4-6", "litellm")
    CLAUDE_SONNET_4_5 = ModelConfig("claude-sonnet-4-5-20250929", "litellm")

    # Google — LiteLLM provider
    GEMINI_3_1_PRO = ModelConfig("gemini-3.1-pro", "litellm")
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

    Routing rules:
    1. If *model* is in :class:`SupportedModel`, use the declared provider
       (``"openai"`` → Responses API, ``"litellm"`` → LiteLLM).
    2. Otherwise, route through LiteLLM and let
       :func:`agent.model_providers.litellm_provider._lookup_rule` decide
       which API key env var is required based on the model name. This
       lets new models drop in without a code change as long as their
       name's substring matches a registered provider rule (claude/anthropic,
       gemini/gemma/learnlm/imagen, or anything added via
       :func:`register_provider`).

    The unknown-model path emits a warning so typos and missing pricing
    entries are visible in the experiment log.
    """
    kwargs: Dict[str, Any] = dict(
        model=model,
        instructions=instructions,
        tools=tools,
        max_output_tokens=max_output_tokens,
        timeout_ms=timeout_ms,
        reasoning_effort=reasoning_effort,
    )

    entry = _MODEL_REGISTRY.get(model)
    if entry is not None:
        if entry.value.provider == "openai":
            return OpenAIProvider(**kwargs)
        return LiteLLMProvider(**kwargs)

    # Unknown model — fall back to LiteLLM with auto-detected provider.
    rule = _lookup_rule(model)
    logger.warning(
        "Model '%s' is not in SupportedModel. Routing through LiteLLM "
        "as %s (env var %s). COST REPORTING WILL BE INCORRECT until you "
        "add a row for '%s' to utils/token_pricing.json: "
        "run_summary.json:metrics.cost_usd will read 0.0 for every call. "
        "Also add an entry to agent/model_providers/factory.py:SupportedModel "
        "to silence this warning. See documentation/ADDING_MODELS.md.",
        model,
        rule.display_name,
        rule.env_var,
        model,
    )
    return LiteLLMProvider(**kwargs)
