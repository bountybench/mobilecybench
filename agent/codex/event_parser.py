"""JSONL event parser for the codex CLI's ``codex exec --json`` stream.

Stateful chunk consumer: ``feed_chunk(text)`` accepts a stdout chunk (may
split a JSONL line across calls), ``flush()`` drains any partial line and
in-flight turn at stream end. Public properties expose aggregated totals.

Extracted from ``codex_cli_provider.CodexCLIProvider.execute`` so both the
legacy docker-SDK path (host invokes codex via ``docker exec``) and the
new in-container path (``agent/codex/run_in_container.py`` invokes codex
via ``subprocess.Popen``) feed the same parser. One source of truth.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from utils.logger import agent_logger, logger


class CodexEventParser:
    """Stateful consumer of codex's ``--json`` event stream."""

    def __init__(self) -> None:
        self.tool_outputs: List[str] = []
        self.assistant_messages: List[str] = []
        self.turn_count = 0
        self.conversation_events: List[Dict[str, Any]] = []
        self.token_usage: Dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
        self.turn_durations: List[float] = []
        self.per_turn_usage: List[Dict[str, Any]] = []
        self.failed_turns = 0
        self.tool_call_breakdown: Dict[str, int] = {}
        self.shell_exit_codes: List[int] = []
        self.thread_id: Optional[str] = None

        # Per-turn accumulators (flushed on turn.completed)
        self._turn_tool_calls: List[Dict[str, Any]] = []
        self._turn_observations: List[Dict[str, Any]] = []
        self._turn_text: List[str] = []

        # Line buffer for chunk boundaries that split a JSONL line.
        self._line_buffer = ""
        self._turn_start_time: Optional[float] = None

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
        else:
            lines.pop()  # trailing empty after final \n

        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                self._handle_event(json.loads(line))
            except json.JSONDecodeError:
                if line:
                    logger.info(f"[Codex Raw] {line}")

    def flush(self) -> None:
        """Drain buffered partial line + any in-flight turn at stream end."""
        if self._line_buffer.strip():
            try:
                self._handle_event(json.loads(self._line_buffer.strip()))
            except json.JSONDecodeError:
                logger.info(f"[Codex Raw] {self._line_buffer.strip()}")
        self._line_buffer = ""
        self._flush_turn()

    def _flush_turn(self) -> None:
        if not self._turn_tool_calls and not self._turn_text:
            return
        self.conversation_events.append(
            {
                "turn": self.turn_count,
                "assistant_text": "\n".join(self._turn_text),
                "tool_calls": list(self._turn_tool_calls),
                "observations": list(self._turn_observations),
            }
        )
        self._turn_tool_calls.clear()
        self._turn_observations.clear()
        self._turn_text.clear()

    def _handle_event(self, data: dict) -> None:
        event_type = data.get("type", "")
        item = data.get("item") or data.get("output_item") or {}
        item_type = item.get("type", "")

        # --- item lifecycle events ---
        if event_type == "item.completed":
            if item_type == "command_execution":
                cmd_str = item.get("command", "")
                item_id = item.get("id", "")
                exit_code = item.get("exit_code")
                if isinstance(exit_code, int):
                    self.shell_exit_codes.append(exit_code)
                self.tool_call_breakdown["shell"] = (
                    self.tool_call_breakdown.get("shell", 0) + 1
                )
                logger.info(f"[Codex Tool] shell: {cmd_str}")
                agent_logger.info("tool_use name=shell command=%s", cmd_str)
                output = item.get("aggregated_output") or item.get("output", "")
                if output:
                    self.tool_outputs.append(output)
                    agent_logger.info("tool_result has_content=%s", bool(output))
                self._turn_tool_calls.append(
                    {
                        "tool_call_id": item_id,
                        "name": "shell",
                        "arguments": {"command": cmd_str},
                    }
                )
                self._turn_observations.append(
                    {
                        "tool_call_id": item_id,
                        "type": "tool_result",
                        "content": output if output else "",
                        "truncated": False,
                    }
                )
            elif item_type == "agent_message":
                text = item.get("text", "")
                if text:
                    self.assistant_messages.append(text)
                    self._turn_text.append(text)
                    logger.info(f"[Codex Message] {text}")
            elif item_type == "function_call":
                name = item.get("name", "unknown")
                item_id = item.get("id", "")
                self.tool_call_breakdown[name] = (
                    self.tool_call_breakdown.get(name, 0) + 1
                )
                logger.info(f"[Codex Tool] {name}")
                agent_logger.info("tool_use name=%s", name)
                self._turn_tool_calls.append(
                    {
                        "tool_call_id": item_id,
                        "name": name,
                        "arguments": item.get("arguments", {}),
                    }
                )
            elif item_type == "function_call_output":
                output = item.get("output", "")
                item_id = item.get("call_id", item.get("id", ""))
                if output:
                    self.tool_outputs.append(output)
                self._turn_observations.append(
                    {
                        "tool_call_id": item_id,
                        "type": "tool_result",
                        "content": output if output else "",
                        "truncated": False,
                    }
                )

        # --- turn lifecycle ---
        elif event_type == "turn.started":
            self._turn_start_time = time.time()

        elif event_type == "turn.completed":
            self.turn_count += 1
            if self._turn_start_time is not None:
                self.turn_durations.append(time.time() - self._turn_start_time)
                self._turn_start_time = None
            usage = data.get("usage", {})
            if usage:
                self.per_turn_usage.append(dict(usage))
                self.token_usage["input_tokens"] += usage.get("input_tokens", 0)
                self.token_usage["output_tokens"] += usage.get("output_tokens", 0)
                cached = usage.get("cached_input_tokens", 0)
                if cached:
                    self.token_usage["cached_input_tokens"] = (
                        self.token_usage.get("cached_input_tokens", 0) + cached
                    )
                # Reasoning tokens: codex hasn't shipped this field yet
                # (tracked upstream in openai/codex#5276); accept either naming.
                reasoning = (
                    usage.get("reasoning_output_tokens")
                    or usage.get("reasoning_tokens")
                    or 0
                )
                if reasoning:
                    self.token_usage["reasoning_output_tokens"] = self.token_usage.get(
                        "reasoning_output_tokens", 0
                    ) + int(reasoning)
            duration_msg = ""
            if self.turn_durations:
                duration_msg = f" ({self.turn_durations[-1]:.1f}s)"
            logger.info(f"[Codex] Turn {self.turn_count} completed{duration_msg}")
            self._flush_turn()

        elif event_type == "turn.failed":
            self.failed_turns += 1
            # Reset so the next turn's duration measures from its own turn.started.
            self._turn_start_time = None
            err = data.get("error") or data.get("message") or {}
            logger.error(f"[Codex] Turn failed: {err}")

        elif event_type == "thread.started":
            tid = data.get("thread_id")
            if isinstance(tid, str):
                self.thread_id = tid

        elif event_type == "error":
            msg = data.get("message", "")
            logger.error(f"[Codex Error] {msg}")

        # --- informational events: ignore ---
        elif event_type in ("item.started",):
            pass

        # --- catch-all ---
        else:
            logger.debug(f"[Codex Event] {event_type}")
