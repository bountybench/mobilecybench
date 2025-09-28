from __future__ import annotations

import os
from typing import Any, Dict, Optional

import anthropic

from .base import ModelProvider


class AnthropicResponse:
    """Wrapper to make Anthropic response compatible with OpenAI interface."""

    def __init__(self, anthropic_response):
        self._response = anthropic_response
        self.output_text = anthropic_response.content[0].text if anthropic_response.content else ""
        self.tool_outputs = []  # Anthropic handles tools differently
        self.output = []  # For MCP interactions
        self.usage = anthropic_response.usage
        self.id = anthropic_response.id


class ClaudeProvider(ModelProvider):
    """Anthropic Claude API provider.

    Wraps client setup, env validation, and message creation calls.
    """

    def __init__(self) -> None:
        # Client is initialized lazily to avoid issues if validation fails
        self._client: Optional[anthropic.Anthropic] = None

    def _client_or_init(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def _test_api_key_connectivity(self) -> None:
        """Attempt a minimal API call to verify the key works."""
        client = self._client_or_init()
        # Test with a simple message
        client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=1,
            messages=[{"role": "user", "content": "Hi"}]
        )

    def validate(self) -> None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key or not api_key.strip():
            raise ValueError(
                "ANTHROPIC_API_KEY environment variable is required but not set. "
                "Please ensure your .env file contains ANTHROPIC_API_KEY=your-actual-key-here "
                "or set the environment variable directly."
            )
        try:
            self._test_api_key_connectivity()
        except Exception as e:
            raise ValueError(
                f"Failed to validate Anthropic API key: {e}. Please ensure your API key is valid."
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

        # Convert input_text to Anthropic message format
        messages = [{"role": "user", "content": input_text}]

        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_output_tokens or 4096,
        }

        # Handle tools - Anthropic has different tool format
        if tools is not None:
            # TODO: Convert tools format if needed
            # For now, we'll skip tools to get basic functionality working
            pass

        if timeout_ms is not None:
            kwargs["timeout"] = timeout_ms / 1000  # Convert to seconds

        if extra:
            kwargs.update(extra)

        response = client.messages.create(**kwargs)
        return AnthropicResponse(response)