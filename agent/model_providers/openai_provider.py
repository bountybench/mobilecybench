from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from openai import OpenAI

from utils.logger import agent_logger

from .base import FunctionCall, ModelProvider, ProviderResponse


class OpenAIProvider(ModelProvider):
    """OpenAI provider using client.responses.create().

    Manages conversation state server-side via previous_response_id.
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
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key or not api_key.strip():
            raise ValueError(
                "OPENAI_API_KEY environment variable is required but not set."
            )
        self._client = OpenAI()
        self._model = model
        self._instructions = instructions
        self._tools = self._convert_tools(tools)
        self._max_output_tokens = max_output_tokens
        self._timeout_ms = timeout_ms
        self._reasoning_effort = reasoning_effort
        self._previous_response_id: str | None = None
        agent_logger.info(f"OpenAI provider configured for model '{model}'")

    def _convert_tools(self, tools: Optional[List]) -> Optional[List]:
        """Convert provider-neutral tool defs to OpenAI Responses API format."""
        if not tools:
            return None
        return [
            {
                "type": "function",
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("parameters", {}),
            }
            for tool in tools
            if isinstance(tool, dict)
        ] or None

    def _parse_output(self, output_items) -> tuple[str, str, list[FunctionCall]]:
        """Parse Responses API output items into normalized fields."""
        assistant_text = ""
        reasoning_summary = ""
        function_calls = []

        for item in output_items:
            item_type = getattr(item, "type", None)

            if item_type == "message":
                for block in getattr(item, "content", []):
                    if getattr(block, "type", None) == "output_text":
                        assistant_text += getattr(block, "text", "")
            elif item_type == "function_call":
                function_calls.append(
                    FunctionCall(
                        name=getattr(item, "name", ""),
                        arguments=getattr(item, "arguments", "{}"),
                        call_id=getattr(item, "call_id", ""),
                    )
                )
            elif item_type == "reasoning":
                for s in getattr(item, "summary", []) or []:
                    reasoning_summary += getattr(s, "text", "")

        return assistant_text, reasoning_summary, function_calls

    def call(self, input: Any) -> ProviderResponse:
        params: Dict[str, Any] = {"model": self._model, "input": input}

        if self._instructions:
            params["instructions"] = self._instructions
        if self._previous_response_id:
            params["previous_response_id"] = self._previous_response_id
        if self._tools:
            params["tools"] = self._tools
        if self._max_output_tokens:
            params["max_output_tokens"] = self._max_output_tokens
        if self._timeout_ms:
            params["timeout"] = self._timeout_ms / 1000.0
        if self._reasoning_effort:
            params["reasoning"] = {
                "effort": self._reasoning_effort,
                "summary": "detailed",
            }
            params["include"] = ["reasoning.encrypted_content"]
        params["truncation"] = "disabled"

        tool_count = len(self._tools) if self._tools else 0
        agent_logger.info(
            f"OpenAI API request: model={self._model}, "
            f"input_type={type(input).__name__}, tools={tool_count}"
            f"{', prev_id=' + self._previous_response_id[:20] + '...' if self._previous_response_id else ''}"
        )

        raw_resp = self._client.responses.create(**params)

        # Update conversation state
        self._previous_response_id = raw_resp.id

        # Parse output into normalized fields
        output_items = getattr(raw_resp, "output", [])
        assistant_text, reasoning_summary, function_calls = self._parse_output(
            output_items
        )

        resp = ProviderResponse(
            response_id=raw_resp.id,
            assistant_text=assistant_text,
            function_calls=function_calls,
            reasoning_summary=reasoning_summary,
            raw_response=raw_resp,
        )
        self._record_history(resp)
        return resp
