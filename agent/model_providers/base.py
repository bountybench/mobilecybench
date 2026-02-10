from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class ModelProvider(ABC):
    """Abstract interface for model providers (thin, per-API wrapper).

    Each provider speaks its native API and returns a normalized response.
    OpenAI uses the Responses API directly; non-OpenAI models go through
    LiteLLM (Chat Completions) with a local conversation state manager
    that translates to/from the Responses API shape.
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
            Provider-specific response object. The caller (CustomAgent) currently
            expects OpenAI Responses API shape (id, output, usage). If adding
            non-OpenAI providers, either adapt the response in the provider or
            introduce a common response wrapper.
            TODO: Define a provider-neutral response dataclass if a second
            provider is added.
        """

    def get_conversation_history(self) -> Optional[List[Dict]]:
        """Return the full conversation history managed by this provider.

        Providers that manage conversation state locally (e.g. LiteLLM) should
        override this to return a JSON-serializable list of history entries.
        Providers that delegate state to the server (e.g. OpenAI via
        previous_response_id) return None.
        """
        return None
