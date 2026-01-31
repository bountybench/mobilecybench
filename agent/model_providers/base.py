from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Union


class ModelProvider(ABC):
    """Abstract interface for model providers.

    Implementations should handle client setup, API key validation,
    and the unified model call used by the agent.
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
        input_messages: Optional[Union[str, list]] = None,
        conversation_id: Optional[str] = None,
        tools: Optional[list] = None,
        max_output_tokens: Optional[int] = None,
        timeout_ms: Optional[int] = None,
        extra: Optional[
            Dict[str, Any]
        ] = None,  # for provider-specific params / extra parameters
    ) -> Any:
        """Perform a model invocation and return a provider-native response.

        Args:
            model: Model identifier
            input_messages: String or list of message objects for model input
            conversation_id: Conversation ID for context
            tools: List of tools available to the model
            max_output_tokens: Maximum tokens in response
            timeout_ms: Request timeout
            extra: Provider-specific parameters
        """
