"""Codex event parser. Subclasses ``BaseEventParser``; the only thing codex-specific
is ``_handle_event``, which maps codex's ``exec --json`` vocabulary onto the base
accumulators.

Codex 0.130 event types we handle (one happy-path run typically emits all five):

    thread.started        — carries thread_id (used as session_id)
    turn.started          — lifecycle marker
    turn.completed        — carries the canonical Usage struct
                            (input/output/reasoning_output/cached_input tokens)
    item.completed/<kind> — kind ∈ {agent_message, reasoning, command_execution,
                            function_call, function_call_output}
    turn.failed / error   — logged

Codex emits no cost field anywhere in its stream (verified against codex-rs
source). Cost is harness-derived from token_totals × token_pricing.json.
"""

from __future__ import annotations

from typing import Any

from agent.in_container.event_parser import BaseEventParser
from utils.logger import agent_logger, logger

# Codex's ``turn.completed.usage`` field names → our canonical token_totals names.
# (verified against codex-rs/exec/src/exec_events.rs)
_USAGE_FIELD_MAP = {
    "input_tokens": "input_tokens",
    "output_tokens": "output_tokens",
    "cached_input_tokens": "cached_input_tokens",
    "reasoning_output_tokens": "reasoning_tokens",
}


class CodexEventParser(BaseEventParser):
    """Stateful consumer of codex's ``--json`` event stream."""

    raw_log_prefix = "Codex"

    def _handle_event(self, data: dict[str, Any]) -> None:
        event_type = data.get("type", "")

        if event_type == "thread.started":
            tid = data.get("thread_id")
            if isinstance(tid, str):
                self.session_id = tid

        elif event_type == "turn.completed":
            self._record_turn_usage(data.get("usage") or {})
            self._flush_turn()

        elif event_type == "turn.failed":
            err = data.get("error") or data.get("message") or {}
            logger.error(f"[Codex] Turn failed: {err}")

        elif event_type == "item.completed":
            self._handle_item(data.get("item") or data.get("output_item") or {})

        elif event_type == "error":
            logger.error(f"[Codex Error] {data.get('message', '')}")

        # turn.started, item.started, etc. — no-op.

    def _handle_item(self, item: dict[str, Any]) -> None:
        item_type = item.get("type", "")

        if item_type == "agent_message":
            text = item.get("text", "")
            if text:
                self._turn_text.append(text)
                logger.info(f"[Codex Message] {text}")

        elif item_type == "reasoning":
            text = item.get("text", "")
            if text:
                self._turn_reasoning.append(text)

        elif item_type == "command_execution":
            cmd = item.get("command", "")
            item_id = item.get("id", "")
            output = item.get("aggregated_output") or item.get("output", "")
            logger.info(f"[Codex Tool] shell: {cmd}")
            agent_logger.info("tool_use name=shell command=%s", cmd)
            if output:
                agent_logger.info("tool_result has_content=%s", bool(output))
            self._turn_tool_calls.append(
                {
                    "tool_call_id": item_id,
                    "name": "shell",
                    "arguments": {"command": cmd},
                }
            )
            self._turn_observations.append(
                {
                    "tool_call_id": item_id,
                    "type": "tool_result",
                    "content": output or "",
                    "truncated": False,
                }
            )

        elif item_type == "function_call":
            name = item.get("name", "unknown")
            item_id = item.get("id", "")
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
            self._turn_observations.append(
                {
                    "tool_call_id": item_id,
                    "type": "tool_result",
                    "content": output or "",
                    "truncated": False,
                }
            )

    def _record_turn_usage(self, usage: dict[str, Any]) -> None:
        if not usage:
            return
        self._accumulate_token_usage(usage, _USAGE_FIELD_MAP)
        self.token_usage.setdefault("input_tokens", 0)
        self.token_usage.setdefault("output_tokens", 0)
