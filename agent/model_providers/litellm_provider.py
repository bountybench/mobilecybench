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
