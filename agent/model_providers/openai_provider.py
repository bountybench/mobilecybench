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

    def validate(self, model: str = None) -> None:
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
        kwargs: Dict[str, Any] = {
            "model": model,
        }

        if conversation_id:
            kwargs["conversation"] = {"id": conversation_id}
            if not input_messages:
                # No input - use format reinforcement as the input
                kwargs["input"] = FORMAT_REINFORCEMENT_MESSAGE
            else:
                # Append format reinforcement to existing input (e.g., tool outputs)
                if isinstance(input_messages, list):
                    kwargs["input"] = input_messages + [
                        {
                            "type": "message",
                            "role": "user",
                            "content": FORMAT_REINFORCEMENT_MESSAGE,
                        }
                    ]
                else:
                    # String input - append reinforcement
                    kwargs["input"] = (
                        f"{input_messages}\n\n{FORMAT_REINFORCEMENT_MESSAGE}"
                    )
        elif input_messages:
            kwargs["input"] = input_messages
        else:
            raise ValueError("Must provide either input_messages or conversation_id")

        if tools is not None:
            kwargs["tools"] = tools
        if max_output_tokens is not None:
            kwargs["max_output_tokens"] = max_output_tokens
        kwargs["max_tool_calls"] = 1
        if timeout_ms is not None:
            kwargs["timeout"] = timeout_ms

        if reasoning_effort:
            kwargs["reasoning"] = {"effort": reasoning_effort}

        if extra:
            kwargs.update(extra)

        agent_logger.info(f"OpenAI API request kwargs: {kwargs}")
        response = client.responses.create(**kwargs)
        return response
