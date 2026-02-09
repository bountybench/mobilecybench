from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class FunctionCall:
    """A single function/tool call from the model."""

    name: str
    arguments: str  # JSON string
    call_id: str


@dataclass
class ProviderResponse:
    """Normalized response from any model provider."""

    response_id: str
    assistant_text: str
    function_calls: List[FunctionCall] = field(default_factory=list)
    reasoning_summary: str = ""
    raw_response: Any = None  # For TokenTracker compatibility


class ModelProvider(ABC):
    """Abstract interface for model providers.

    **Design contract:** Providers are *stateful* — each instance owns its
    conversation state (message history, response chaining, etc.).  The agent
    (``CustomAgent``) is *stateless* with respect to conversation: it passes
    new input each turn and reads back a normalized ``ProviderResponse``.

    Lifecycle:
        1. ``get_model_provider(model, instructions, ...)`` — factory picks the
           right subclass and returns a fully configured, ready-to-use instance.
        2. ``provider.call(input)`` — per-turn invocation; returns ``ProviderResponse``.
        3. ``provider.get_conversation_history()`` — structured log for archiving.

    How state is managed per provider:
        - **OpenAIProvider** — server-side via ``previous_response_id``.
        - **LiteLLMProvider** — client-side via an accumulated messages array.
    """

    def __init__(self) -> None:
        self._conversation_history: List[Dict] = []

    # -- Shared helpers (concrete) -----------------------------------------

    def _record_history(self, resp: "ProviderResponse") -> None:
        """Append a normalized history entry for *resp*.

        Called by each provider at the end of ``call()`` to keep a
        single source of truth for the conversation log format.
        """
        self._conversation_history.append(
            {
                "turn": len(self._conversation_history) + 1,
                "response_id": resp.response_id,
                "assistant_text": resp.assistant_text,
                "reasoning_summary": resp.reasoning_summary,
                "function_calls": [
                    {
                        "name": fc.name,
                        "call_id": fc.call_id,
                        "arguments": fc.arguments,
                    }
                    for fc in resp.function_calls
                ],
            }
        )

    def get_conversation_history(self) -> List[Dict]:
        """Return structured conversation history for archiving/observability.

        Returns:
            List of dicts, each with keys: turn, response_id, assistant_text,
            reasoning_summary, function_calls.
        """
        return list(self._conversation_history)

    # -- Abstract methods (must be implemented) ----------------------------

    @abstractmethod
    def call(self, input: Any) -> ProviderResponse:
        """Perform a model invocation with new input.

        Args:
            input: Input string or list of input items (tool results, user messages)

        Returns:
            ProviderResponse with normalized fields.
        """
