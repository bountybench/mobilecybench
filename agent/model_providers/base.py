from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class ModelProvider(ABC):
    """Abstract interface for model providers.

    Each provider wraps a specific API (OpenAI, Anthropic, Google, etc.)
    behind a common interface for agentic tool-use workflows.
    Providers handle provider-specific details (auth, parameter mapping,
    response format) while exposing a uniform call() signature.
    """

    @abstractmethod
    def validate(self, model: str = None) -> None:
        """Validate environment/configuration (e.g., API keys).

        Args:
            model: Optional model name to validate specific provider API key.

        Should raise a ValueError with a clear message if invalid/missing.
        """

    @abstractmethod
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
        """Perform a model invocation.

        Args:
            model: Model identifier (e.g., "gpt-5.2")
            input: Input string or list of input items (tool results, user messages)
            tools: Optional list of tool definitions
            max_output_tokens: Maximum tokens in response
            timeout_ms: Request timeout in milliseconds
            reasoning_effort: For reasoning models (provider maps to native format)
            instructions: System-level instructions
            previous_response_id: ID of previous response for conversation continuity
            **kwargs: Provider-specific parameters

        Returns:
            Response object with:
            - id: Response ID (used as previous_response_id for next call)
            - output: List of output items (messages, function_calls, reasoning)
            - usage: Token usage information
        """
