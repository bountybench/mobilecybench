from __future__ import annotations

import os
from typing import Any, Dict, Optional
from openai import OpenAI

from .base import ModelProvider


class OpenAIProvider(ModelProvider):
    """OpenAI Responses API provider.

    Wraps client setup, env validation, and `responses.create` calls.
    """

    def __init__(self) -> None:
        # Client is initialized lazily to avoid issues if validation fails
        self._client: Optional[OpenAI] = None

    def _client_or_init(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI()
        return self._client

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
        except Exception as e:
            raise ValueError(
                f"Failed to validate OpenAI API key: {e}. Please ensure your API key is valid."
            )

    def call(
        self,
        *,
        model: str,
        input_text: str,
        tools: Optional[list] = None,
        max_output_tokens: Optional[int] = None,
        timeout_ms: Optional[int] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Any:
        client = self._client_or_init()
        kwargs: Dict[str, Any] = {
            "model": model,
            "input": input_text,
        }
        if tools is not None:
            kwargs["tools"] = tools
        if max_output_tokens is not None:
            kwargs["max_output_tokens"] = max_output_tokens
        if timeout_ms is not None:
            kwargs["timeout"] = timeout_ms
        if extra:
            kwargs.update(extra)

        return client.responses.create(**kwargs)
