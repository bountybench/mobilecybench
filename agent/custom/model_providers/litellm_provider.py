"""LiteLLM provider for non-OpenAI models (Anthropic, Gemini, etc.).

Implements the stateful ModelProvider interface. Manages conversation
state client-side via an accumulated messages array, translating between
the Responses API input format used by custom_agent.py and LiteLLM's
Chat Completions interface.

LiteLLM routes by model name. Built-in detection rules live in
``_PROVIDER_REGISTRY``; add an entry there to map your model's name
substring to its API-key env var and (optional) LiteLLM dialect prefix.
For runtime registration without editing this file, call
:func:`register_provider`.

See ``documentation/ADDING_MODELS.md`` for the end-to-end checklist.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import litellm

from utils.logger import agent_logger

from .base import FunctionCall, ModelProvider, ProviderResponse

# Suppress LiteLLM's verbose logging
litellm.suppress_debug_info = True


@dataclass(frozen=True)
class ProviderRule:
    """One row of the provider-detection registry.

    Attributes:
        patterns: Substrings to match against the lowercased model id.
        provider: Canonical provider tag (e.g. "anthropic", "gemini").
        env_var: Environment variable that must hold the API key.
        display_name: Human-readable name surfaced in logs.
        litellm_prefix: Optional prefix LiteLLM expects on the model id
            (e.g. "gemini/"). When set, the prefix is added if missing.
    """

    patterns: Tuple[str, ...]
    provider: str
    env_var: str
    display_name: str
    litellm_prefix: str = ""


# Detection registry. The first matching rule wins. To add a provider,
# either append to this list at import time or call register_provider().
_PROVIDER_REGISTRY: List[ProviderRule] = [
    ProviderRule(
        patterns=("gemini", "gemma", "learnlm", "imagen"),
        provider="gemini",
        env_var="GEMINI_API_KEY",
        display_name="Google Gemini",
        litellm_prefix="gemini/",
    ),
    ProviderRule(
        patterns=("claude", "anthropic"),
        provider="anthropic",
        env_var="ANTHROPIC_API_KEY",
        display_name="Anthropic",
    ),
]

# Fallback when nothing matches.
_DEFAULT_RULE = ProviderRule(
    patterns=(),
    provider="openai",
    env_var="OPENAI_API_KEY",
    display_name="OpenAI",
)


def register_provider(
    patterns: Tuple[str, ...],
    provider: str,
    env_var: str,
    display_name: str,
    litellm_prefix: str = "",
) -> None:
    """Register a provider rule for LiteLLM model-name detection.

    Newly registered rules are inserted at the front of the registry so
    they take precedence over the built-in providers. This lets integrators
    override defaults without editing this file.

    Args:
        patterns: Tuple of substrings; case-insensitive match against the
            model id selects this rule.
        provider: Canonical short tag (e.g. "myprovider").
        env_var: Environment variable that must contain the API key.
        display_name: Human-readable name for logs.
        litellm_prefix: Optional prefix that LiteLLM expects on the model
            id (e.g. "openai/"). The prefix is added if missing.
    """
    if not patterns:
        raise ValueError("patterns must contain at least one substring")
    rule = ProviderRule(
        patterns=tuple(patterns),
        provider=provider,
        env_var=env_var,
        display_name=display_name,
        litellm_prefix=litellm_prefix,
    )
    _PROVIDER_REGISTRY.insert(0, rule)


def lookup_rule(model: str) -> ProviderRule:
    """Return the provider-detection rule that matches *model*.

    Walks `_PROVIDER_REGISTRY` in order; the first rule whose substrings
    appear in the lowercased model id wins. Falls back to `_DEFAULT_RULE`
    (OpenAI) when nothing matches.
    """
    model_lower = model.lower()
    for rule in _PROVIDER_REGISTRY:
        if any(p in model_lower for p in rule.patterns):
            return rule
    return _DEFAULT_RULE


class LiteLLMProvider(ModelProvider):
    """LiteLLM-based provider for non-OpenAI models.

    Translates to/from Chat Completions format and maintains conversation
    state so that custom_agent.py can use it identically to OpenAIProvider.
    """

    def __init__(
        self,
        model: str,
        instructions: str,
        tools: Optional[List[Dict]] = None,
        max_output_tokens: Optional[int] = None,
        timeout_ms: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
    ) -> None:
        super().__init__()
        litellm.set_verbose = False

        rule = lookup_rule(model)

        # Validate API key
        api_key = os.getenv(rule.env_var)
        if not api_key or not api_key.strip():
            raise ValueError(
                f"{rule.env_var} environment variable is required but not set. "
                f"Please ensure your .env file contains {rule.env_var}=your-actual-key-here "
                "or set the environment variable directly."
            )

        self._model = model
        self._rule = rule
        self._litellm_model = self._apply_litellm_prefix(model, rule)
        self._tools = self._convert_tools_to_litellm(tools)
        self._max_output_tokens = max_output_tokens
        self._timeout_ms = timeout_ms
        self._reasoning_effort = reasoning_effort

        # Conversation state (Chat Completions messages list)
        self._messages: List[Dict[str, Any]] = [
            {"role": "system", "content": instructions}
        ]

        agent_logger.info(
            f"{rule.display_name} provider configured for model '{model}'"
        )

    @staticmethod
    def _apply_litellm_prefix(model: str, rule: ProviderRule) -> str:
        """Add the rule's LiteLLM prefix if not already present."""
        if rule.litellm_prefix and not model.startswith(rule.litellm_prefix):
            return f"{rule.litellm_prefix}{model}"
        return model

    def _convert_tools_to_litellm(self, tools: Optional[List]) -> Optional[List]:
        """Convert tool definitions to LiteLLM/OpenAI Chat Completions format."""
        if not tools:
            return None

        litellm_tools = []
        for tool in tools:
            if isinstance(tool, dict):
                if "function" in tool:
                    litellm_tools.append(tool)
                elif "name" in tool and "parameters" in tool:
                    litellm_tools.append(
                        {
                            "type": "function",
                            "function": {
                                "name": tool["name"],
                                "description": tool.get("description", ""),
                                "parameters": tool["parameters"],
                            },
                        }
                    )

        return litellm_tools if litellm_tools else None

    def _translate_input_to_messages(self, input: Any) -> List[Dict[str, Any]]:
        """Convert Responses-API-style input into Chat Completions messages."""
        if isinstance(input, str):
            return [{"role": "user", "content": input}]

        if not isinstance(input, list):
            return [{"role": "user", "content": str(input)}]

        messages: List[Dict[str, Any]] = []
        for item in input:
            if not isinstance(item, dict):
                continue

            item_type = item.get("type")

            if item_type == "message":
                role = item.get("role", "user")
                content = item.get("content", "")

                if isinstance(content, list):
                    parts: List[Dict[str, Any]] = []
                    for part in content:
                        part_type = part.get("type", "")
                        if part_type == "input_image":
                            image_url = part.get("image_url", "")
                            parts.append(
                                {
                                    "type": "image_url",
                                    "image_url": {"url": image_url},
                                }
                            )
                        elif part_type == "input_text":
                            parts.append({"type": "text", "text": part.get("text", "")})
                        else:
                            parts.append({"type": "text", "text": str(part)})
                    messages.append({"role": role, "content": parts})
                else:
                    messages.append({"role": role, "content": content})

            elif item_type == "function_call_output":
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": item.get("call_id", ""),
                        "content": item.get("output", ""),
                    }
                )

        return messages

    def call(self, input: Any) -> ProviderResponse:
        # Translate input and append to conversation
        new_messages = self._translate_input_to_messages(input)
        self._messages.extend(new_messages)

        # Build completion kwargs from stored config
        completion_kwargs: Dict[str, Any] = {
            "model": self._litellm_model,
            "messages": list(self._messages),
        }

        if self._tools:
            completion_kwargs["tools"] = self._tools
            completion_kwargs["tool_choice"] = "auto"
            # parallel_tool_calls is only supported by OpenAI-compatible APIs
            if self._rule.provider == "openai":
                completion_kwargs["parallel_tool_calls"] = False

        if self._max_output_tokens:
            completion_kwargs["max_tokens"] = self._max_output_tokens

        if self._timeout_ms:
            completion_kwargs["timeout"] = self._timeout_ms / 1000.0

        if self._reasoning_effort:
            completion_kwargs["reasoning_effort"] = self._reasoning_effort

        tool_count = len(self._tools) if self._tools else 0
        agent_logger.info(
            f"LiteLLM API request: model={self._litellm_model}, "
            f"messages={len(self._messages)}, tools={tool_count}"
        )

        # Make the API call
        raw_response = litellm.completion(**completion_kwargs)

        # Parse response
        choice = raw_response.choices[0] if raw_response.choices else None
        message = choice.message if choice else None

        assistant_text = ""
        reasoning_summary = ""
        function_calls = []

        if message:
            assistant_text = getattr(message, "content", None) or ""
            reasoning_summary = getattr(message, "reasoning_content", None) or ""

            tool_calls = getattr(message, "tool_calls", None) or []
            for tc in tool_calls:
                fn = tc.function
                call_id = tc.id or f"call_{uuid.uuid4().hex[:24]}"
                function_calls.append(
                    FunctionCall(
                        name=fn.name,
                        arguments=fn.arguments,
                        call_id=call_id,
                    )
                )

        # Append full message to conversation state, preserving thinking
        # blocks and provider-specific fields for round-trip fidelity.
        assistant_msg = (
            message.model_dump()
            if message and hasattr(message, "model_dump")
            else {"role": "assistant", "content": assistant_text}
        )
        self._messages.append(assistant_msg)

        response_id = getattr(raw_response, "id", None) or ""

        resp = ProviderResponse(
            response_id=response_id,
            assistant_text=assistant_text,
            function_calls=function_calls,
            reasoning_summary=reasoning_summary,
            raw_response=raw_response,
        )
        self._record_history(resp)
        return resp
