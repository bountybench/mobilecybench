from __future__ import annotations

import os
from typing import Any, Dict, Optional

import google.generativeai as genai

from .base import ModelProvider


class GeminiResponse:
    """Wrapper to make Gemini response compatible with OpenAI interface."""

    def __init__(self, gemini_response):
        self._response = gemini_response
        self.output_text = gemini_response.text if hasattr(gemini_response, 'text') else ""
        self.tool_outputs = []  # Gemini handles tools differently
        self.output = []  # For MCP interactions
        # Extract usage statistics from Gemini response
        self.usage = self._create_usage_from_response(gemini_response)
        self.id = None  # Gemini responses don't have IDs like OpenAI

    def _create_usage_from_response(self, gemini_response):
        """Extract real usage data from Gemini response."""
        class GeminiUsage:
            def __init__(self, input_tokens=0, output_tokens=0, total_tokens=0):
                self.input_tokens = input_tokens
                self.output_tokens = output_tokens
                self.total_tokens = total_tokens

        # Try to extract real usage data
        if hasattr(gemini_response, 'usage_metadata'):
            usage = gemini_response.usage_metadata
            input_tokens = getattr(usage, 'prompt_token_count', 0)
            output_tokens = getattr(usage, 'candidates_token_count', 0)
            total_tokens = getattr(usage, 'total_token_count', input_tokens + output_tokens)

            return GeminiUsage(input_tokens, output_tokens, total_tokens)

        # Fallback to mock if usage data not available
        return GeminiUsage(0, 0, 0)


class GeminiProvider(ModelProvider):
    """Google Gemini API provider.

    Wraps client setup, env validation, and generation calls.
    """

    def __init__(self) -> None:
        # Client is initialized lazily to avoid issues if validation fails
        self._initialized = False

    def _init_client(self) -> None:
        """Initialize the Gemini client."""
        if not self._initialized:
            api_key = os.getenv("GOOGLE_API_KEY")
            genai.configure(api_key=api_key)
            self._initialized = True

    def _test_api_key_connectivity(self) -> None:
        """Attempt a minimal API call to verify the key works."""
        self._init_client()
        # Test with a simple generation
        model = genai.GenerativeModel('gemini-pro')
        response = model.generate_content("Hi")
        # If we get here without exception, the API key works

    def validate(self) -> None:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key or not api_key.strip():
            raise ValueError(
                "GOOGLE_API_KEY environment variable is required but not set. "
                "Please ensure your .env file contains GOOGLE_API_KEY=your-actual-key-here "
                "or set the environment variable directly."
            )
        try:
            self._test_api_key_connectivity()
        except Exception as e:
            raise ValueError(
                f"Failed to validate Google API key: {e}. Please ensure your API key is valid."
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
        self._init_client()

        # Create the model instance
        gemini_model = genai.GenerativeModel(model)

        # Prepare generation config
        generation_config = {}
        if max_output_tokens is not None:
            generation_config['max_output_tokens'] = max_output_tokens

        # Handle tools - Gemini has different tool format
        if tools is not None:
            # TODO: Convert tools format if needed
            # For now, we'll skip tools to get basic functionality working
            pass

        # Handle timeout - Gemini doesn't have direct timeout support
        # We might need to implement this at a higher level

        if extra:
            generation_config.update(extra)

        # Generate content
        if generation_config:
            response = gemini_model.generate_content(
                input_text,
                generation_config=genai.types.GenerationConfig(**generation_config)
            )
        else:
            response = gemini_model.generate_content(input_text)

        return GeminiResponse(response)