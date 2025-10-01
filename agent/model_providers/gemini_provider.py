from __future__ import annotations

import os
from typing import Any, Dict, Optional

from google import genai
from google.genai import types

from .base import ModelProvider


class GeminiProvider(ModelProvider):
    """Google Gemini API provider.

    Wraps client setup, env validation, and Gemini API calls.
    """

    def __init__(self) -> None:
        # Client is initialized lazily to avoid issues if validation fails
        self._client: Optional[genai.Client] = None
        self._timeout_ms: Optional[int] = None

    def _client_or_init(self, timeout_ms: Optional[int] = None) -> genai.Client:
        # Reinitialize client if timeout changes
        if self._client is None or (timeout_ms is not None and timeout_ms != self._timeout_ms):
            api_key = os.getenv("GEMINI_API_KEY")
            http_options = None
            if timeout_ms is not None:
                http_options = types.HttpOptions(timeout=timeout_ms)
            self._client = genai.Client(api_key=api_key, http_options=http_options)
            self._timeout_ms = timeout_ms
        return self._client

    def _test_api_key_connectivity(self) -> None:
        """Attempt a minimal API call to verify the key works."""
        client = self._client_or_init()
        # Test with a simple generate_content call using stable model
        client.models.generate_content(
            model="gemini-2.5-flash",
            contents="Hi"
        )

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
        # Initialize client with timeout if provided
        client = self._client_or_init(timeout_ms=timeout_ms)

        # Prepare generation config
        config_kwargs: Dict[str, Any] = {}

        if max_output_tokens is not None:
            config_kwargs["max_output_tokens"] = max_output_tokens

        if tools is not None:
            # Convert tools to Gemini function declarations format
            function_declarations = []
            for tool in tools:
                if "function" in tool:
                    func_def = tool["function"]
                    function_declarations.append({
                        "name": func_def.get("name"),
                        "description": func_def.get("description", ""),
                        "parameters": func_def.get("parameters", {})
                    })

            if function_declarations:
                tool_config = types.Tool(function_declarations=function_declarations)
                config_kwargs["tools"] = [tool_config]

        if extra:
            config_kwargs.update(extra)

        config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

        # Prepare request arguments
        request_kwargs: Dict[str, Any] = {
            "model": model,
            "contents": input_text,
        }

        if config:
            request_kwargs["config"] = config

        response = client.models.generate_content(**request_kwargs)

        # Wrap response to match expected interface
        class GeminiResponse:
            def __init__(self, gemini_response):
                self._response = gemini_response

            @property
            def output_text(self) -> str:
                try:
                    # Safely extract text from response
                    if hasattr(self._response, 'text') and self._response.text:
                        return self._response.text
                    # Fallback to candidates if text property fails
                    if hasattr(self._response, 'candidates') and self._response.candidates:
                        candidate = self._response.candidates[0]
                        if hasattr(candidate, 'content') and candidate.content:
                            text_parts = []
                            for part in candidate.content.parts:
                                if hasattr(part, 'text') and part.text:
                                    text_parts.append(part.text)
                            return ''.join(text_parts)
                except Exception:
                    pass
                return ""

            @property
            def tool_outputs(self) -> list:
                tool_calls = []
                try:
                    if hasattr(self._response, 'candidates') and self._response.candidates:
                        candidate = self._response.candidates[0]
                        if hasattr(candidate, 'content') and candidate.content:
                            for part in candidate.content.parts:
                                if hasattr(part, 'function_call') and part.function_call:
                                    func_call = part.function_call
                                    tool_calls.append({
                                        'name': func_call.name,
                                        'input': dict(func_call.args) if hasattr(func_call, 'args') else {}
                                    })
                except Exception:
                    pass
                return tool_calls

            @property
            def output(self) -> list:
                # MCP interaction records - implement as needed
                return []

        return GeminiResponse(response)