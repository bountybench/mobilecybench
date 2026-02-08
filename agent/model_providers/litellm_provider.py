"""LiteLLM provider adapted for OpenAI Responses API interface.

Accepts the same call() signature as OpenAIProvider (input, instructions,
previous_response_id) and translates between the Responses API format used
by custom_agent.py and LiteLLM's Chat Completions interface.  Conversation
state is managed locally rather than on the server.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import litellm

from utils.logger import agent_logger

from .base import ModelProvider

# Suppress LiteLLM's verbose logging
litellm.suppress_debug_info = True


# Lightweight wrapper classes that mimic OpenAI Responses API objects so that
# custom_agent.py can use getattr() / attribute access identically.
class _ContentBlock:
    """Mirrors a Responses API output_text content block."""

    def __init__(self, text: str) -> None:
        self.type = "output_text"
        self.text = text


class _OutputMessage:
    """Mirrors a Responses API message output item."""

    def __init__(self, content_blocks: List[_ContentBlock]) -> None:
        self.type = "message"
        self.content = content_blocks


class _FunctionCall:
    """Mirrors a Responses API function_call output item."""

    def __init__(self, name: str, arguments: str, call_id: str) -> None:
        self.type = "function_call"
        self.name = name
        self.arguments = arguments
        self.call_id = call_id


class _TokenDetails:
    """Mirrors prompt_tokens_details / input_tokens_details from the API."""

    def __init__(self, cached_tokens: int) -> None:
        self.cached_tokens = cached_tokens


class _UsageInfo:
    """Mirrors Responses API usage with attribute access.

    Also exposes prompt_tokens / completion_tokens aliases and
    prompt_tokens_details / input_tokens_details so that the
    token tracker's _extract_token_count helper works out of the box.
    """

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
        # Aliases for Chat Completions convention
        self.prompt_tokens = input_tokens
        self.completion_tokens = output_tokens
        # Cache details — exposed in both formats for the token tracker
        details = _TokenDetails(cached_tokens)
        self.prompt_tokens_details = details
        self.input_tokens_details = details


class _ResponsesAPIResponse:
    """Top-level response wrapper matching the Responses API shape."""

    def __init__(
        self,
        id: str,
        output: list,
        usage: _UsageInfo,
    ) -> None:
        self.id = id
        self.output = output
        self.usage = usage


class LiteLLMProvider(ModelProvider):
    """LiteLLM-based provider that presents a Responses API interface.

    Internally translates to/from Chat Completions format and maintains
    conversation state so that custom_agent.py can use it identically to
    OpenAIProvider.
    """

    def __init__(self) -> None:
        self._validated: bool = False

        # Configure LiteLLM settings
        litellm.drop_params = True  # Drop unsupported params instead of erroring
        litellm.set_verbose = False  # Reduce noise in logs

        # Conversation state (Chat Completions messages list)
        self._messages: List[Dict[str, Any]] = []

        # Observability history
        self._history: List[Dict[str, Any]] = []
        self._turn: int = 0

    def _detect_provider_from_model(self, model: str) -> str:
        """Detect the provider from the model name."""
        model_lower = model.lower()

        if any(p in model_lower for p in ["gemini", "gemma", "learnlm", "imagen"]):
            return "gemini"
        if any(p in model_lower for p in ["claude", "anthropic"]):
            return "anthropic"
        if any(
            p in model_lower
            for p in ["gpt", "o1", "o3", "o4", "davinci", "curie", "babbage", "ada"]
        ):
            return "openai"

        # Default to OpenAI
        return "openai"

    def _get_litellm_model_name(self, model: str) -> str:
        """Convert model name to LiteLLM format if needed.

        Gemini models require a gemini/ prefix for LiteLLM.
        Anthropic and OpenAI models are auto-detected and need no prefix.
        """
        model_lower = model.lower()

        if any(p in model_lower for p in ["gemini", "gemma", "learnlm"]):
            if not model.startswith("gemini/"):
                return f"gemini/{model}"

        return model

    def _get_required_api_key_env(self, model: str) -> tuple[str, str]:
        """Get the required API key environment variable for a model."""
        provider = self._detect_provider_from_model(model)

        if provider == "gemini":
            return "GEMINI_API_KEY", "Google Gemini"
        if provider == "anthropic":
            return "ANTHROPIC_API_KEY", "Anthropic"
        return "OPENAI_API_KEY", "OpenAI"

    def validate(self, model: str = None) -> None:
        if model:
            env_var, provider_name = self._get_required_api_key_env(model)
        else:
            env_var, provider_name = "OPENAI_API_KEY", "OpenAI"

        api_key = os.getenv(env_var)
        if not api_key or not api_key.strip():
            raise ValueError(
                f"{env_var} environment variable is required but not set. "
                f"Please ensure your .env file contains {env_var}=your-actual-key-here "
                "or set the environment variable directly."
            )

        self._validated = True
        agent_logger.info(
            f"{provider_name} API key found for model '{model or 'default'}'"
        )

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
        """Convert Responses-API-style *input* into Chat Completions messages."""
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
                    # Multimodal content (e.g. input_image)
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

    def _translate_response(self, response: Any) -> _ResponsesAPIResponse:
        """Convert a LiteLLM ChatCompletion response into a Responses-API-like wrapper."""
        choice = response.choices[0] if response.choices else None
        message = choice.message if choice else None

        output_items: list = []
        assistant_msg: Dict[str, Any] = {"role": "assistant"}

        if message:
            # Text content
            text = getattr(message, "content", None) or ""
            if text:
                output_items.append(_OutputMessage([_ContentBlock(text)]))
                assistant_msg["content"] = text

            # Tool calls
            tool_calls = getattr(message, "tool_calls", None) or []
            if tool_calls:
                tc_list = []
                for tc in tool_calls:
                    fn = tc.function
                    call_id = tc.id or f"call_{uuid.uuid4().hex[:24]}"
                    output_items.append(
                        _FunctionCall(
                            name=fn.name,
                            arguments=fn.arguments,
                            call_id=call_id,
                        )
                    )
                    tc_list.append(
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": fn.name,
                                "arguments": fn.arguments,
                            },
                        }
                    )
                assistant_msg["tool_calls"] = tc_list
                # When there are tool calls, content may be None
                if "content" not in assistant_msg:
                    assistant_msg["content"] = None

        # Append assistant message to conversation state
        self._messages.append(assistant_msg)

        # Build usage
        usage_obj = getattr(response, "usage", None)
        input_tokens = getattr(usage_obj, "prompt_tokens", 0) or 0
        output_tokens = getattr(usage_obj, "completion_tokens", 0) or 0
        total_tokens = getattr(usage_obj, "total_tokens", 0) or 0

        # Extract cache tokens from the raw response (LiteLLM passes through
        # prompt_tokens_details.cached_tokens for providers that support it)
        cached_tokens = 0
        raw_details = getattr(usage_obj, "prompt_tokens_details", None)
        if raw_details:
            ct = getattr(raw_details, "cached_tokens", None)
            if ct is not None:
                cached_tokens = int(ct)

        usage = _UsageInfo(input_tokens, output_tokens, total_tokens, cached_tokens)

        response_id = f"litellm_{uuid.uuid4().hex}"

        # Record to history
        self._history.append(
            {
                "turn": self._turn,
                "role": "assistant",
                "content": assistant_msg.get("content"),
                "tool_calls": assistant_msg.get("tool_calls"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "token_usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens,
                },
            }
        )

        return _ResponsesAPIResponse(
            id=response_id,
            output=output_items,
            usage=usage,
        )

    def call(
        self,
        *,
        model: str,
        input: Any,
        tools: Optional[List[Dict]] = None,
        max_output_tokens: Optional[int] = None,
        timeout_ms: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
        instructions: Optional[str] = None,
        previous_response_id: Optional[str] = None,
        **kwargs,
    ) -> Any:
        """Perform a model invocation using the Responses API interface.

        Translates between the Responses API format (used by custom_agent.py)
        and LiteLLM's Chat Completions format.
        """
        if not self._validated:
            raise RuntimeError(
                "LiteLLM provider not validated. Call validate() before making API calls."
            )

        self._turn += 1
        litellm_model = self._get_litellm_model_name(model)

        # On first call (or when instructions change), set/reset system message
        if instructions and (
            not self._messages
            or self._messages[0].get("role") != "system"
            or self._messages[0].get("content") != instructions
        ):
            if self._messages and self._messages[0].get("role") == "system":
                self._messages[0] = {"role": "system", "content": instructions}
            else:
                self._messages.insert(0, {"role": "system", "content": instructions})

            self._history.append(
                {
                    "turn": self._turn,
                    "role": "system",
                    "content": instructions,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

        # Translate Responses API input → Chat Completions messages
        new_messages = self._translate_input_to_messages(input)

        # Record user / tool messages in history
        for msg in new_messages:
            entry: Dict[str, Any] = {
                "turn": self._turn,
                "role": msg["role"],
                "content": msg.get("content"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            if msg.get("tool_call_id"):
                entry["tool_call_id"] = msg["tool_call_id"]
            self._history.append(entry)

        # Append to running conversation
        self._messages.extend(new_messages)

        # Build completion kwargs
        completion_kwargs: Dict[str, Any] = {
            "model": litellm_model,
            "messages": list(self._messages),  # copy
        }

        # Add tools
        litellm_tools = self._convert_tools_to_litellm(tools)
        if litellm_tools:
            completion_kwargs["tools"] = litellm_tools
            completion_kwargs["tool_choice"] = "auto"
            completion_kwargs["parallel_tool_calls"] = False

        if max_output_tokens:
            completion_kwargs["max_tokens"] = max_output_tokens

        if timeout_ms:
            completion_kwargs["timeout"] = timeout_ms / 1000.0

        # Handle reasoning/thinking for supported models
        if reasoning_effort:
            provider = self._detect_provider_from_model(model)

            if provider == "openai":
                completion_kwargs["reasoning_effort"] = reasoning_effort
            elif provider == "gemini":
                budget = kwargs.pop("thinking_budget", None)
                if budget is None:
                    budget = 8192
                    if "low" in reasoning_effort:
                        budget = 2048
                    elif "high" in reasoning_effort:
                        budget = 16384
                completion_kwargs["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": budget,
                }
            elif provider == "anthropic":
                budget = kwargs.pop("thinking_budget", None)
                if budget is None:
                    budget = 8192
                    if "low" in reasoning_effort:
                        budget = 2048
                    elif "high" in reasoning_effort:
                        budget = 16384
                completion_kwargs["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": budget,
                }

        # Extra kwargs
        completion_kwargs.update(kwargs)

        agent_logger.info(
            f"LiteLLM API request: model={litellm_model}, "
            f"messages={len(self._messages)}, "
            f"tools={len(litellm_tools) if litellm_tools else 0}"
        )

        # Make the API call
        raw_response = litellm.completion(**completion_kwargs)

        # Translate to Responses API wrapper and update internal state
        return self._translate_response(raw_response)

    def get_conversation_history(self) -> Optional[List[Dict]]:
        """Return the full conversation history for observability.

        Each entry includes role, content, optional tool_calls / tool_call_id,
        turn number, timestamp, and token_usage (for assistant turns).
        """
        return list(self._history)
