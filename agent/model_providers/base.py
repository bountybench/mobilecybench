from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class ModelProvider(ABC):
    """Abstract interface for model providers.

    Implementations should handle client setup, API key validation,
    and the unified model call used by the agent.

    The provider is stateless - the agent manages conversation history.
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
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        max_output_tokens: Optional[int] = None,
        timeout_ms: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
        **kwargs,
    ) -> Any:
        """Perform a model invocation and return a ChatCompletion response.

        Args:
            model: Model identifier (e.g., "gpt-4", "claude-3-opus")
            messages: List of message dicts with role and content
            tools: Optional list of tool definitions
            max_output_tokens: Maximum tokens in response
            timeout_ms: Request timeout in milliseconds
            reasoning_effort: For reasoning models (o1, etc.)
            **kwargs: Provider-specific parameters

        Returns:
            ChatCompletion response object with:
            - choices[0].message.content: Response text
            - choices[0].message.tool_calls: List of tool calls (if any)
            - usage: Token usage information
        """
