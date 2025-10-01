from __future__ import annotations

import os
from typing import Any, Dict, Optional

import anthropic

from .base import ModelProvider


class AnthropicProvider(ModelProvider):
    """Anthropic Claude API provider.

    Wraps client setup, env validation, and Claude API calls.
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
        # Test with a simple message creation to verify API key
        client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=10,
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

        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": input_text}],
            "max_tokens": max_output_tokens or 1000,
        }

        if tools is not None:
            kwargs["tools"] = tools

        if timeout_ms is not None:
            kwargs["timeout"] = timeout_ms / 1000.0  # Convert to seconds

        # Handle extra parameters (including system prompts)
        # System prompts should be passed as extra={"system": "your system prompt"}
        if extra:
            kwargs.update(extra)

        response = client.messages.create(**kwargs)

        # Wrap response to match expected interface
        class AnthropicResponse:
            def __init__(self, anthropic_response):
                self._response = anthropic_response

            @property
            def output_text(self) -> str:
                if self._response.content and len(self._response.content) > 0:
                    # Handle text content blocks
                    text_blocks = [
                        block.text for block in self._response.content
                        if hasattr(block, 'text')
                    ]
                    return ''.join(text_blocks)
                return ""

            @property
            def tool_outputs(self) -> list:
                tool_calls = []
                if self._response.content:
                    for block in self._response.content:
                        if hasattr(block, 'type') and block.type == 'tool_use':
                            tool_calls.append({
                                'id': block.id,
                                'name': block.name,
                                'input': block.input
                            })
                return tool_calls

            @property
            def output(self) -> list:
                # MCP interaction records - implement as needed
                return []

        return AnthropicResponse(response)