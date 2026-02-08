from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from openai import OpenAI

from utils.logger import agent_logger

from .base import ModelProvider


class OpenAIProvider(ModelProvider):
    """OpenAI provider using client.responses.create()."""

    def __init__(self) -> None:
        self._validated = False
        self._client: OpenAI | None = None

    def validate(self, model: str = None) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key or not api_key.strip():
            raise ValueError(
                "OPENAI_API_KEY environment variable is required but not set."
            )
        self._client = OpenAI()
        self._validated = True
        agent_logger.info(f"OpenAI API key found for model '{model or 'default'}'")

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
        if not self._validated or not self._client:
            raise RuntimeError("Provider not validated. Call validate() first.")

        params: Dict[str, Any] = {"model": model, "input": input}

        if instructions:
            params["instructions"] = instructions
        if previous_response_id:
            params["previous_response_id"] = previous_response_id

        resp_tools = self._convert_tools(tools)
        if resp_tools:
            params["tools"] = resp_tools
        if max_output_tokens:
            params["max_output_tokens"] = max_output_tokens
        if timeout_ms:
            params["timeout"] = timeout_ms / 1000.0
        params["reasoning"] = {
            "effort": reasoning_effort or "medium",
            "summary": "detailed",
        }
        params["include"] = ["reasoning.encrypted_content"]
        params["truncation"] = "auto"

        params.update(kwargs)

        tool_count = len(resp_tools) if resp_tools else 0
        agent_logger.info(
            f"OpenAI API request: model={model}, "
            f"input_type={type(input).__name__}, tools={tool_count}"
            f"{', prev_id=' + previous_response_id[:20] + '...' if previous_response_id else ''}"
        )

        return self._client.responses.create(**params)
