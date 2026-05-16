"""JSONL event parser for the claude CLI's ``--output-format stream-json`` stream.

Same shape as :mod:`agent.codex.event_parser`: feeds CLI output chunk by
chunk via ``feed_chunk``, drains on ``flush``, then ``emit_turns`` /
``summarize`` materialize ``conversation.jsonl`` + ``result.json``.
"""

from __future__ import annotations

import datetime
import json
from typing import Any, Dict, List, Optional

from utils.logger import agent_logger, logger


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class ClaudeCodeEventParser:
    """Stateful consumer of claude's ``--output-format stream-json`` stream."""

    def __init__(self) -> None:
        self.tool_outputs: List[str] = []
        self.assistant_messages: List[str] = []
        self.conversation_events: List[Dict[str, Any]] = []
        self.result_turns = 0
        self.result_cost: Optional[float] = None
        self.session_id: Optional[str] = None
        self.result_payload: Optional[Dict[str, Any]] = None

        # Per-turn accumulators (schema requires turn_number >= 1).
        self._current_turn = 1
        self._turn_text: List[str] = []
        self._turn_tool_calls: List[Dict[str, Any]] = []
        self._turn_observations: List[Dict[str, Any]] = []
        self._turn_reasoning: List[str] = []

        # Line buffer for chunk boundaries.
        self._line_buffer = ""

    @property
    def final_output(self) -> str:
        return "\n".join(self.assistant_messages)

    def feed_chunk(self, text: str) -> None:
        """Consume a stdout chunk; parse complete lines, buffer remainder."""
        text = self._line_buffer + text
        self._line_buffer = ""

        lines = text.split("\n")
        if not text.endswith("\n"):
            self._line_buffer = lines.pop()

        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                self._handle_event(json.loads(line))
            except json.JSONDecodeError:
                if line:
                    logger.info(f"[ClaudeCode Raw] {line}")

    def flush(self) -> None:
        """Drain buffered partial line + any in-flight turn at stream end."""
        if self._line_buffer.strip():
            try:
                self._handle_event(json.loads(self._line_buffer.strip()))
            except json.JSONDecodeError:
                logger.info(f"[ClaudeCode Raw] {self._line_buffer.strip()}")
        self._line_buffer = ""
        self._flush_turn()

    def _flush_turn(self) -> None:
        if not self._turn_text and not self._turn_tool_calls:
            return
        self.conversation_events.append(
            {
                "turn": self._current_turn,
                "timestamp": _utc_now_iso(),
                "assistant_text": "\n".join(self._turn_text),
                "reasoning_summary": "\n".join(self._turn_reasoning),
                "tool_calls": list(self._turn_tool_calls),
                "observations": list(self._turn_observations),
            }
        )
        self._turn_text.clear()
        self._turn_tool_calls.clear()
        self._turn_observations.clear()
        self._turn_reasoning.clear()
        self._current_turn += 1

    def _handle_event(self, data: dict) -> None:
        event_type = data.get("type")

        if event_type == "system":
            if data.get("subtype") == "init":
                self.session_id = data.get("session_id", "unknown")
                logger.info(f"[ClaudeCode] Session started: {self.session_id}")

        elif event_type == "assistant":
            for content in data.get("message", {}).get("content", []):
                ctype = content.get("type")
                if ctype == "text":
                    text = content.get("text", "")
                    if text:
                        self.assistant_messages.append(text)
                        self._turn_text.append(text)
                        logger.info(f"[ClaudeCode Message] {text}")
                elif ctype == "thinking":
                    thinking = content.get("thinking", "")
                    if thinking:
                        self._turn_reasoning.append(thinking)
                elif ctype == "tool_use":
                    name = content.get("name", "unknown")
                    args = content.get("input", {})
                    call_id = content.get("id", "")
                    self._turn_tool_calls.append(
                        {
                            "name": name,
                            "tool_call_id": call_id,
                            "arguments": args,
                        }
                    )
                    logger.info(f"[ClaudeCode Tool] {name} input={json.dumps(args)}")
                    agent_logger.info(
                        "tool_use name=%s input=%s", name, json.dumps(args)
                    )

        elif event_type == "user":
            for content in data.get("message", {}).get("content", []):
                if content.get("type") == "tool_result":
                    self.tool_outputs.append(json.dumps(content))
                    raw = content.get("content", "")
                    if isinstance(raw, list):
                        body = "\n".join(b.get("text", str(b)) for b in raw)
                    else:
                        body = raw
                    self._turn_observations.append(
                        {
                            "tool_use_id": content.get("tool_use_id", ""),
                            "content": body,
                        }
                    )
                    agent_logger.info("tool_result content=%s", body)
            # A user event (tool results) marks the end of a turn.
            self._flush_turn()

        elif event_type == "result":
            self.result_turns = data.get("num_turns", 0)
            self.result_cost = data.get("total_cost_usd")
            self.result_payload = data
            self._flush_turn()
            subtype = data.get("subtype")
            if subtype == "success":
                cost_str = f"${self.result_cost:.4f}" if self.result_cost else "N/A"
                logger.info(
                    f"[ClaudeCode] Completed: {self.result_turns} turns, cost={cost_str}"
                )
            elif subtype == "error":
                logger.error(f"[ClaudeCode] Error: {data.get('error')}")

    def emit_turns(self, task: Dict[str, Any], path: str) -> None:
        """Materialize parser state as conversation_turn JSONL records."""
        timestamp = _utc_now_iso()
        with open(path, "w", encoding="utf-8") as f:
            for ev in self.conversation_events:
                f.write(json.dumps({
                    "run_id": task["run_id"],
                    "turn_number": ev["turn"],
                    "timestamp": timestamp,
                    "role": "assistant",
                    "response_id": None,
                    "assistant_text": ev["assistant_text"],
                    "reasoning_summary": ev.get("reasoning_summary", ""),
                    "tool_calls": ev["tool_calls"],
                    "observations": [
                        {
                            "tool_call_id": obs.get("tool_use_id", ""),
                            "type": "tool_result",
                            "content": obs.get("content", ""),
                            "truncated": False,
                        }
                        for obs in ev.get("observations", [])
                    ],
                    "status": "ok",
                }, ensure_ascii=False) + "\n")

    def summarize(
        self, task: Dict[str, Any], exit_code: int, elapsed: float
    ) -> Dict[str, Any]:
        status = "completed" if exit_code == 0 else "error"
        tool_call_count = sum(
            len(e["tool_calls"]) for e in self.conversation_events
        )
        unique_tools = sorted({
            tc["name"]
            for e in self.conversation_events
            for tc in e["tool_calls"]
        })
        result: Dict[str, Any] = {
            "status": status,
            "turns_taken": self.result_turns or len(self.conversation_events),
            "cost_usd": self.result_cost or 0,
            "model": task.get("model", ""),
            "final_message": self.final_output,
            "tool_call_count": tool_call_count,
            "unique_tools": unique_tools,
            "token_totals": (self.result_payload or {}).get("usage", {}),
            "exit_code": exit_code,
        }
        if status == "error":
            result["error_traceback"] = (
                f"claude exit_code={exit_code}, elapsed={elapsed:.1f}s"
            )
        return result
