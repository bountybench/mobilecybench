from __future__ import annotations

import os
from typing import Any, Dict, Optional, Union

from openai import OpenAI

from utils.logger import agent_logger
from utils.model_utils import FORMAT_REINFORCEMENT_MESSAGE

from .base import ModelProvider


class OpenAIProvider(ModelProvider):
    """OpenAI Responses API provider.

    Wraps client setup, env validation, and `responses.create` calls.

    Uses a 2-phase approach for tool calls:
    - Phase 1: Generate text output (no tools)
    - Phase 2: Generate tool call (tools required)

    This is necessary because OpenAI models treat text and tool calls as
    mutually exclusive output channels, unlike Gemini which combines them.
    """

    def __init__(self) -> None:
        # Client is initialized lazily to avoid issues if validation fails
        self._client: Optional[OpenAI] = None
        self._validated: bool = False

    def _client_or_init(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI()
        return self._client

    @property
    def client(self) -> OpenAI:
        if not self._validated:
            raise RuntimeError(
                "OpenAI provider not validated. Call validate() before accessing client."
            )
        return self._client_or_init()

    def _test_api_key_connectivity(self) -> None:
        """Attempt a minimal API call to verify the key works."""
        client = self._client_or_init()
        client.models.list()

    def validate(self) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key or not api_key.strip():
            raise ValueError(
                "OPENAI_API_KEY environment variable is required but not set. "
                "Please ensure your .env file contains OPENAI_API_KEY=your-actual-key-here "
                "or set the environment variable directly."
            )
        try:
            self._test_api_key_connectivity()
            self._validated = True
        except Exception as e:
            raise ValueError(
                f"Failed to validate OpenAI API key: {e}. Please ensure your API key is valid."
            )

    def call(
        self,
        *,
        model: str,
        input_messages: Optional[Union[str, list]] = None,
        conversation_id: Optional[str] = None,
        tools: Optional[list] = None,
        max_output_tokens: Optional[int] = None,
        timeout_ms: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Any:
        client = self._client_or_init()

        base_kwargs: Dict[str, Any] = {"model": model}

        if conversation_id:
            base_kwargs["conversation"] = {"id": conversation_id}
            if not input_messages:
                base_kwargs["input"] = FORMAT_REINFORCEMENT_MESSAGE
            else:
                if isinstance(input_messages, list):
                    base_kwargs["input"] = input_messages + [
                        {
                            "type": "message",
                            "role": "user",
                            "content": FORMAT_REINFORCEMENT_MESSAGE,
                        }
                    ]
                else:
                    base_kwargs["input"] = (
                        f"{input_messages}\n\n{FORMAT_REINFORCEMENT_MESSAGE}"
                    )
        elif input_messages:
            base_kwargs["input"] = input_messages
        else:
            raise ValueError("Must provide either input_messages or conversation_id")

        if max_output_tokens is not None:
            base_kwargs["max_output_tokens"] = max_output_tokens
        if timeout_ms is not None:
            base_kwargs["timeout"] = timeout_ms

        if reasoning_effort:
            base_kwargs["reasoning"] = {"effort": reasoning_effort, "summary": "auto"}
            base_kwargs["include"] = ["reasoning.encrypted_content"]

        if extra:
            base_kwargs.update(extra)

        if tools:
            # Phase 1: Get text output (no tools)
            phase1_kwargs = base_kwargs.copy()
            agent_logger.info(f"OpenAI API Phase 1 (text): {phase1_kwargs}")
            text_response = client.responses.create(**phase1_kwargs)

            # Phase 2: Get tool call (with tools, force tool use)
            phase2_kwargs = base_kwargs.copy()
            phase2_kwargs["tools"] = tools
            phase2_kwargs["tool_choice"] = "required"
            phase2_kwargs["max_tool_calls"] = 1

            # Feed Phase 1 output into Phase 2 input
            if text_response.output_text:
                if isinstance(phase2_kwargs["input"], list):
                    # Append assistant message to list
                    phase2_kwargs["input"] = list(phase2_kwargs["input"])
                    phase2_kwargs["input"].append(
                        {"role": "assistant", "content": text_response.output_text}
                    )
                elif isinstance(phase2_kwargs["input"], str):
                    # Append text to string
                    phase2_kwargs["input"] += f"\n\n{text_response.output_text}"

            agent_logger.info(f"OpenAI API Phase 2 (tool): {phase2_kwargs}")
            tool_response = client.responses.create(**phase2_kwargs)

            # Merge: text from phase 1, tool calls from phase 2
            return self._merge_responses(text_response, tool_response)
        else:
            # No tools - single phase
            agent_logger.info(f"OpenAI API request kwargs: {base_kwargs}")
            return client.responses.create(**base_kwargs)

    def _merge_responses(self, text_response: Any, tool_response: Any) -> Any:
        """Merge text response and tool response into a single response object."""

        # Create a simple wrapper that combines both responses
        class MergedResponse:
            def __init__(self, text_resp, tool_resp):
                self._text_resp = text_resp
                self._tool_resp = tool_resp

            @property
            def output_text(self):
                return self._text_resp.output_text

            @property
            def output(self):
                # Combine output items from both responses
                items = []
                if hasattr(self._text_resp, "output") and self._text_resp.output:
                    items.extend(self._text_resp.output)
                if hasattr(self._tool_resp, "output") and self._tool_resp.output:
                    items.extend(self._tool_resp.output)
                return items

            @property
            def tool_calls(self):
                return getattr(self._tool_resp, "tool_calls", [])

            @property
            def id(self):
                return self._tool_resp.id

            @property
            def usage(self):
                # Combine usage from both responses
                text_usage = getattr(self._text_resp, "usage", None)
                tool_usage = getattr(self._tool_resp, "usage", None)
                if text_usage and tool_usage:

                    class CombinedUsage:
                        def __init__(self, u1, u2):
                            self.input_tokens = getattr(
                                u1, "input_tokens", 0
                            ) + getattr(u2, "input_tokens", 0)
                            self.output_tokens = getattr(
                                u1, "output_tokens", 0
                            ) + getattr(u2, "output_tokens", 0)
                            self.total_tokens = getattr(
                                u1, "total_tokens", 0
                            ) + getattr(u2, "total_tokens", 0)

                    return CombinedUsage(text_usage, tool_usage)
                return tool_usage or text_usage

            def __getattr__(self, name):
                # Fallback to tool_response for any other attributes
                return getattr(self._tool_resp, name)

        return MergedResponse(text_response, tool_response)
