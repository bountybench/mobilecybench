"""OpenAI Responses API provider.

Uses the OpenAI Responses API with previous_response_id for conversation state.
Converts responses to Chat Completions format for compatibility with the agent.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import litellm

from utils.logger import agent_logger

from .base import ModelProvider


class OpenAIResponsesProvider(ModelProvider):
    """Provider for OpenAI Responses API.

    Uses previous_response_id to maintain conversation state server-side.
    Converts Responses API output to Chat Completions format for compatibility.
    """

    def __init__(self) -> None:
        self._validated: bool = False
        self._previous_response_id: Optional[str] = None
        self._instructions: Optional[str] = None

    def _get_model_name(self, model: str) -> str:
        """Extract clean model name, removing any prefixes."""
        if model.startswith("openai/responses/"):
            return model[len("openai/responses/"):]
        if model.startswith("openai/"):
            return model[len("openai/"):]
        return model

    def validate(self, model: str = None) -> None:
        """Validate that OPENAI_API_KEY is set."""
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key or not api_key.strip():
            raise ValueError("OPENAI_API_KEY environment variable is required but not set.")

        self._validated = True
        agent_logger.info(f"OpenAI API key found for model '{model or 'default'}'")

    def _convert_tools(self, tools: Optional[List]) -> Optional[List]:
        """Convert tool definitions to Responses API format."""
        if not tools:
            return None

        responses_tools = []
        for tool in tools:
            if isinstance(tool, dict):
                # Handle both flat and nested formats
                if "function" in tool:
                    func = tool["function"]
                else:
                    func = tool

                responses_tools.append({
                    "type": "function",
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "parameters": func.get("parameters", {}),
                })

        return responses_tools if responses_tools else None

    def _build_input(self, messages: List[Dict[str, Any]]) -> List[Dict]:
        """Build input items from messages for Responses API.

        Only processes messages that need to be sent (new since last response).
        """
        input_items = []

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")

            if role == "system":
                # System message becomes instructions (stored, sent on first call)
                if self._instructions is None:
                    self._instructions = content

            elif role == "user":
                input_items.append({
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": content}]
                })

            elif role == "tool":
                # Tool result
                input_items.append({
                    "type": "function_call_output",
                    "call_id": msg.get("tool_call_id", ""),
                    "output": content
                })

            # Skip assistant messages - they're tracked via previous_response_id

        return input_items

    def _get_new_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract only new messages since the last assistant response."""
        new_messages = []

        # Find messages after the last assistant message
        for msg in reversed(messages):
            if msg.get("role") == "assistant":
                break
            new_messages.insert(0, msg)

        return new_messages

    def _convert_response(self, response: Any) -> Any:
        """Convert Responses API response to Chat Completions format."""
        output = getattr(response, "output", []) or []

        content_parts = []
        tool_calls = []

        for item in output:
            item_type = getattr(item, "type", None)

            if item_type == "message":
                msg_content = getattr(item, "content", []) or []
                for part in msg_content:
                    if getattr(part, "type", None) == "output_text":
                        content_parts.append(getattr(part, "text", ""))

            elif item_type == "function_call":
                tool_calls.append(SimpleNamespace(
                    id=getattr(item, "call_id", getattr(item, "id", "")),
                    type="function",
                    function=SimpleNamespace(
                        name=getattr(item, "name", ""),
                        arguments=getattr(item, "arguments", "{}"),
                    ),
                ))

        # Store response ID for next call
        self._previous_response_id = getattr(response, "id", None)

        # Build Chat Completions compatible response
        message = SimpleNamespace(
            content="\n".join(content_parts) if content_parts else "",
            tool_calls=tool_calls if tool_calls else None,
        )

        choice = SimpleNamespace(
            index=0,
            message=message,
            finish_reason="tool_calls" if tool_calls else "stop",
        )

        return SimpleNamespace(
            id=getattr(response, "id", ""),
            choices=[choice],
            usage=getattr(response, "usage", None),
            model=getattr(response, "model", ""),
        )

    def call(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        max_output_tokens: Optional[int] = None,
        timeout_ms: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
        thinking_budget: Optional[int] = None,
        **kwargs,
    ) -> Any:
        """Call the OpenAI Responses API.

        Args:
            model: Model identifier
            messages: Full message history (will extract new messages only)
            tools: Tool definitions
            max_output_tokens: Maximum tokens in response
            timeout_ms: Request timeout in milliseconds
            reasoning_effort: Reasoning effort level
            **kwargs: Additional arguments

        Returns:
            Chat Completions compatible response object
        """
        if not self._validated:
            raise RuntimeError("Provider not validated. Call validate() first.")

        model_name = self._get_model_name(model)

        # Build request
        request: Dict[str, Any] = {"model": model_name}

        # Determine what to send based on conversation state
        if self._previous_response_id:
            # Continuing conversation - send only new messages
            request["previous_response_id"] = self._previous_response_id
            new_messages = self._get_new_messages(messages)
            input_items = self._build_input(new_messages)
        else:
            # First call - process all messages, send instructions
            input_items = self._build_input(messages)
            if self._instructions:
                request["instructions"] = self._instructions

        request["input"] = input_items

        # Send tools on every call - Responses API doesn't persist them
        if tools:
            responses_tools = self._convert_tools(tools)
            if responses_tools:
                request["tools"] = responses_tools
                request["tool_choice"] = "auto"

        # Optional parameters
        if max_output_tokens:
            request["max_output_tokens"] = max_output_tokens

        if timeout_ms:
            request["timeout"] = timeout_ms / 1000.0

        if reasoning_effort:
            request["reasoning"] = {"effort": reasoning_effort}

        agent_logger.info(
            f"Responses API: model={model_name}, "
            f"input_items={len(input_items)}, "
            f"tools={len(request.get('tools', []))}, "
            f"has_previous_response={self._previous_response_id is not None}"
        )

        # Make the API call via LiteLLM
        response = litellm.responses(**request)

        return self._convert_response(response)
