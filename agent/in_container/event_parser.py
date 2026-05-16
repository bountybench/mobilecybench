"""Base parser for BYO CLIs that emit a line-delimited event stream.

Subclasses override one method: ``_handle_event(data: dict)`` which maps the
CLI's event vocabulary onto the per-turn / run accumulators below. Everything
else — line buffering, turn flushing, conversation-row formatting, summary
shape — is owned here.

Run-wide accumulators a subclass should populate as events arrive:
    self.assistant_messages: list[str]
    self.token_usage: dict[str, int]
    self.session_id: str | None
    self.stop_reason: str | None
    self.agent_reported_cost: float | None    # set only when the CLI emits cost
    self.agent_reported_turns: int | None     # set only when the CLI emits a turn count
    self.timing: dict[str, int]               # {api_ms, ttft_ms} when CLI exposes

Per-turn accumulators — fill these in ``_handle_event``, then call ``_flush_turn``
when the CLI's turn boundary fires:
    self._turn_text: list[str]
    self._turn_tool_calls: list[dict]         # canonical {tool_call_id, name, arguments}
    self._turn_observations: list[dict]       # canonical {tool_call_id, type, content, truncated}
    self._turn_reasoning: list[str]
"""

from __future__ import annotations

import datetime
import json
from abc import ABC, abstractmethod
from typing import Any

from utils.logger import logger


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class BaseEventParser(ABC):
    """Stateful consumer of a CLI's line-delimited event stream."""

    raw_log_prefix: str = "Event"  # override per CLI (e.g. "Codex", "ClaudeCode")

    def __init__(self) -> None:
        # Run-wide.
        self.conversation_events: list[dict[str, Any]] = []
        self.assistant_messages: list[str] = []
        self.token_usage: dict[str, int] = {}
        self.session_id: str | None = None
        self.stop_reason: str | None = None
        self.agent_reported_cost: float | None = None
        self.agent_reported_turns: int | None = None
        self.timing: dict[str, int] = {}

        # Per-turn (cleared on _flush_turn).
        self._turn_text: list[str] = []
        self._turn_tool_calls: list[dict[str, Any]] = []
        self._turn_observations: list[dict[str, Any]] = []
        self._turn_reasoning: list[str] = []

        # Stream-internal.
        self._line_buffer: str = ""
        self._drained: int = 0

    @property
    def final_output(self) -> str:
        return "\n".join(self.assistant_messages)

    def feed_chunk(self, text: str) -> None:
        """Parse complete lines out of the next stdout chunk; buffer the remainder."""
        text = self._line_buffer + text
        self._line_buffer = ""
        lines = text.split("\n")
        if not text.endswith("\n"):
            self._line_buffer = lines.pop()
        for line in lines:
            self._consume_line(line)

    def flush(self) -> None:
        """Drain the buffered partial line + any in-flight turn at stream end."""
        if self._line_buffer.strip():
            self._consume_line(self._line_buffer)
        self._line_buffer = ""
        self._flush_turn()

    def drain_records(self, task: dict[str, Any]) -> list[dict[str, Any]]:
        """Format the conversation events flushed since the last drain.

        The runner calls this after every ``feed_chunk`` so partial-state runs
        leave usable telemetry on disk even after a hard kill.
        """
        start = self._drained
        end = len(self.conversation_events)
        records = [
            self._format_record(task, self.conversation_events[i])
            for i in range(start, end)
        ]
        self._drained = end
        return records

    def summarize(
        self, task: dict[str, Any], exit_code: int, elapsed: float
    ) -> dict[str, Any]:
        """Build the result.json shape from accumulated state.

        Cost resolution does NOT happen here — the host-side
        ``utils.run_artifacts.normalize_agent_result`` reads
        ``cost_usd`` if the agent emitted one and derives otherwise.
        """
        status = "completed" if exit_code == 0 else "error"
        turns_taken = (
            self.agent_reported_turns
            if self.agent_reported_turns is not None
            else len(self.conversation_events)
        )
        tool_call_count = sum(len(e["tool_calls"]) for e in self.conversation_events)
        unique_tools = sorted(
            {tc["name"] for e in self.conversation_events for tc in e["tool_calls"]}
        )

        result: dict[str, Any] = {
            "status": status,
            "turns_taken": turns_taken,
            "model": task.get("model", ""),
            "final_message": self.final_output,
            "exit_code": exit_code,
            "tool_call_count": tool_call_count,
            "unique_tools": unique_tools,
            "token_totals": dict(self.token_usage),
        }
        if self.agent_reported_cost is not None:
            result["cost_usd"] = self.agent_reported_cost
        if self.session_id is not None:
            result["session_id"] = self.session_id
        if self.stop_reason is not None:
            result["stop_reason"] = self.stop_reason
        if self.timing:
            result["timing"] = dict(self.timing)
        if status == "error":
            result["error_traceback"] = (
                f"{self.raw_log_prefix} exit_code={exit_code}, elapsed={elapsed:.1f}s"
            )
        return result

    # --- subclass surface ---

    @abstractmethod
    def _handle_event(self, data: dict[str, Any]) -> None:
        """Map one parsed CLI event onto the per-turn / run accumulators."""

    # --- internal ---

    def _consume_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        try:
            self._handle_event(json.loads(line))
        except json.JSONDecodeError:
            logger.info(f"[{self.raw_log_prefix} Raw] {line}")

    def _flush_turn(self) -> None:
        """Snapshot the current turn into ``conversation_events`` and reset accumulators."""
        if not self._turn_text and not self._turn_tool_calls:
            return
        self.conversation_events.append(
            {
                "turn_number": len(self.conversation_events) + 1,
                "assistant_text": "\n".join(self._turn_text),
                "reasoning_summary": "\n".join(self._turn_reasoning),
                "tool_calls": list(self._turn_tool_calls),
                "observations": list(self._turn_observations),
                "timestamp": _utc_now_iso(),
            }
        )
        self._turn_text.clear()
        self._turn_tool_calls.clear()
        self._turn_observations.clear()
        self._turn_reasoning.clear()

    def _format_record(
        self, task: dict[str, Any], event: dict[str, Any]
    ) -> dict[str, Any]:
        """Materialize one ``conversation_events`` entry as a BYO-contract JSONL row."""
        return {
            "run_id": task["run_id"],
            "turn_number": event["turn_number"],
            "timestamp": event["timestamp"],
            "role": "assistant",
            "response_id": None,
            "assistant_text": event["assistant_text"],
            "reasoning_summary": event["reasoning_summary"],
            "tool_calls": event["tool_calls"],
            "observations": event["observations"],
            "status": "ok",
        }
