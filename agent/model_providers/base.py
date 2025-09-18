from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class ModelProvider(ABC):
    """Abstract interface for model providers.

    Implementations should handle client setup, API key validation,
    and the unified model call used by the agent.
    """

    @abstractmethod
    def validate(self) -> None:
        """Validate environment/configuration (e.g., API keys).

        Should raise a ValueError with a clear message if invalid/missing.
        """

    @abstractmethod
    def call(
        self,
        *,
        model: str,
        input_text: str,
        tools: Optional[list] = None,
        max_output_tokens: Optional[int] = None,
        timeout_ms: Optional[int] = None,
        extra: Optional[
            Dict[str, Any]
        ] = None,  # for provider-specific params / extra parameters
    ) -> Any:
        """Perform a model invocation and return a provider-native response.

        The response expose attributes used by the agent:
        For current OpenAI implementation, these are:
        - `output_text` (str)
        - `tool_outputs` (list)
        - `output` (list) with MCP interaction records
        """
