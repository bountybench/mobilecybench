from __future__ import annotations

import os
from typing import Any, Dict, Optional

import google.generativeai as genai

from .base import ModelProvider


class GeminiProvider(ModelProvider):
    """Google Gemini API provider.

    Wraps client setup, env validation, and Gemini API calls.
    """

    def __init__(self) -> None:
        # Client is initialized lazily to avoid issues if validation fails
        self._client_configured = False

    def _configure_client(self) -> None:
        if not self._client_configured:
            api_key = os.getenv("GEMINI_API_KEY")
            genai.configure(api_key=api_key)
            self._client_configured = True

    def _test_api_key_connectivity(self) -> None:
        """Attempt a minimal API call to verify the key works."""
        self._configure_client()
        # Test with a simple list models call
        list(genai.list_models())

    def validate(self) -> None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key or not api_key.strip():
            raise ValueError(
                "GEMINI_API_KEY environment variable is required but not set. "
                "Please ensure your .env file contains GEMINI_API_KEY=your-actual-key-here "
                "or set the environment variable directly."
            )
        try:
            self._test_api_key_connectivity()
        except Exception as e:
            raise ValueError(
                f"Failed to validate Gemini API key: {e}. Please ensure your API key is valid."
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
        self._configure_client()

        # Create the model instance
        model_instance = genai.GenerativeModel(model)

        # Prepare generation config
        generation_config = {}
        if max_output_tokens is not None:
            generation_config["max_output_tokens"] = max_output_tokens
        if extra:
            generation_config.update(extra)

        # Generate content
        response = model_instance.generate_content(
            input_text,
            generation_config=generation_config if generation_config else None,
        )

        # Wrap response to match expected interface
        class GeminiResponse:
            def __init__(self, gemini_response):
                self._response = gemini_response

            @property
            def output_text(self) -> str:
                return self._response.text if self._response.text else ""

            @property
            def tool_outputs(self) -> list:
                # Gemini tool usage would need to be implemented based on specific requirements
                return []

            @property
            def output(self) -> list:
                # MCP interaction records - implement as needed
                return []

        return GeminiResponse(response)