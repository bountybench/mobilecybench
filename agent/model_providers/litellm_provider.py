"""LiteLLM provider for non-OpenAI models (Anthropic, Gemini, etc.).

Implements the stateful ModelProvider interface. Manages conversation
state client-side via an accumulated messages array, translating between
the Responses API input format used by custom_agent.py and LiteLLM's
Chat Completions interface.
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List, Optional

import litellm

from utils.logger import agent_logger

from .base import FunctionCall, ModelProvider, ProviderResponse

# Suppress LiteLLM's verbose logging
litellm.suppress_debug_info = True


# Lightweight wrappers for TokenTracker compatibility


class _TokenDetails:
    def __init__(self, cached_tokens: int) -> None:
        self.cached_tokens = cached_tokens


class _UsageInfo:
    def __init__(
        self,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        cached_tokens: int = 0,
    ) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_tokens = total_tokens
        self.prompt_tokens = input_tokens
        self.completion_tokens = output_tokens
        details = _TokenDetails(cached_tokens)
        self.prompt_tokens_details = details
        self.input_tokens_details = details


class _RawResponseWrapper:
    """Minimal wrapper for raw_response so TokenTracker can read .id and .usage."""

    def __init__(self, id: str, usage: _UsageInfo) -> None:
        self.id = id
        self.usage = usage


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

        # Validate API key
        env_var, provider_name = self._get_required_api_key_env(model)
        api_key = os.getenv(env_var)
        if not api_key or not api_key.strip():
            raise ValueError(
                f"{env_var} environment variable is required but not set. "
                f"Please ensure your .env file contains {env_var}=your-actual-key-here "
                "or set the environment variable directly."
            )

        self._model = model
        self._litellm_model = self._get_litellm_model_name(model)
        self._tools = self._convert_tools_to_litellm(tools)
        self._max_output_tokens = max_output_tokens
        self._timeout_ms = timeout_ms
        self._reasoning_effort = reasoning_effort

        # Conversation state (Chat Completions messages list)
        self._messages: List[Dict[str, Any]] = [
            {"role": "system", "content": instructions}
        ]

        agent_logger.info(f"{provider_name} provider configured for model '{model}'")

    def _detect_provider_from_model(self, model: str) -> str:
        model_lower = model.lower()
        if any(p in model_lower for p in ["gemini", "gemma", "learnlm", "imagen"]):
            return "gemini"
        if any(p in model_lower for p in ["claude", "anthropic"]):
            return "anthropic"
        return "openai"

    def _get_litellm_model_name(self, model: str) -> str:
        """Gemini models require a gemini/ prefix for LiteLLM."""
        model_lower = model.lower()
        if any(p in model_lower for p in ["gemini", "gemma", "learnlm"]):
            if not model.startswith("gemini/"):
                return f"gemini/{model}"
        return model

    def _get_required_api_key_env(self, model: str) -> tuple[str, str]:
        provider = self._detect_provider_from_model(model)
        if provider == "gemini":
            return "GEMINI_API_KEY", "Google Gemini"
        if provider == "anthropic":
            return "ANTHROPIC_API_KEY", "Anthropic"
        return "OPENAI_API_KEY", "OpenAI"

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
            if self._detect_provider_from_model(self._model) == "openai":
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
            message.model_dump() if message and hasattr(message, "model_dump")
            else {"role": "assistant", "content": assistant_text}
        )
        self._messages.append(assistant_msg)

        # Build usage wrapper for token tracker
        usage_obj = getattr(raw_response, "usage", None)
        input_tokens = getattr(usage_obj, "prompt_tokens", 0) or 0
        output_tokens = getattr(usage_obj, "completion_tokens", 0) or 0
        total_tokens = getattr(usage_obj, "total_tokens", 0) or 0

        cached_tokens = 0
        raw_details = getattr(usage_obj, "prompt_tokens_details", None)
        if raw_details is not None:
            if isinstance(raw_details, dict):
                ct = raw_details.get("cached_tokens")
            else:
                ct = getattr(raw_details, "cached_tokens", None)
            if ct is not None:
                cached_tokens = int(ct)

        response_id = f"litellm_{uuid.uuid4().hex}"
        usage = _UsageInfo(input_tokens, output_tokens, total_tokens, cached_tokens)
        raw_wrapper = _RawResponseWrapper(id=response_id, usage=usage)

        resp = ProviderResponse(
            response_id=response_id,
            assistant_text=assistant_text,
            function_calls=function_calls,
            reasoning_summary=reasoning_summary,
            raw_response=raw_wrapper,
        )
        self._record_history(resp)
        return resp
