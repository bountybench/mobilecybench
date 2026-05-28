"""Opencode event parser. Subclasses ``BaseEventParser``; the only thing
opencode-specific is ``_handle_event``, which maps opencode's
``--format json`` event vocabulary onto the base accumulators.

opencode 1.15.x event types we handle:

    step_start  — lifecycle marker; first one carries the session id
    text        — finalized assistant text part
    reasoning   — provider-side reasoning text (may be empty)
    tool_use    — completed/errored tool part with name, args, output
    step_finish — per-step tokens (input/output/reasoning/cache) + USD cost
    error       — terminal: opencode runs session.idle then exits, often 0,
                  so terminal_error forces result.status="error".
"""

from __future__ import annotations

import json
from typing import Any

from agent.in_container.event_parser import BaseEventParser
from utils.logger import agent_logger, logger

# step_finish.tokens names -> canonical token_totals. opencode emits
# per-step (not cumulative) values, so we sum across step_finish events.
_USAGE_FIELD_MAP = {
    "input": "input_tokens",
    "output": "output_tokens",
    "reasoning": "reasoning_tokens",
}
_CACHE_FIELD_MAP = {
    "read": "cached_input_tokens",
    "write": "cache_creation_tokens",
}


class OpencodeEventParser(BaseEventParser):
    """Stateful consumer of opencode's ``--format json`` event stream."""

    raw_log_prefix = "Opencode"

    def _handle_event(self, data: dict[str, Any]) -> None:
        event_type = data.get("type", "")

        if event_type == "step_start":
            sid = data.get("sessionID")
            if isinstance(sid, str) and self.session_id is None:
                self.session_id = sid

        elif event_type == "text":
            text = (data.get("part") or {}).get("text") or ""
            if text:
                self._turn_text.append(text)
                logger.info(f"[Opencode Message] {text}")

        elif event_type == "reasoning":
            text = (data.get("part") or {}).get("text") or ""
            if text:
                self._turn_reasoning.append(text)

        elif event_type == "tool_use":
            self._handle_tool_use(data.get("part") or {})

        elif event_type == "step_finish":
            self._handle_step_finish(data.get("part") or {})

        elif event_type == "error":
            err = data.get("error") or {}
            if isinstance(err, dict):
                name = err.get("name", "Error")
                msg = (err.get("data") or {}).get("message") or name
            else:
                name, msg = "Error", str(err)
            # Tentative: opencode emits `error` for both terminal failures
            # (auth, run-ending) and recoverable mid-run failures (Read ENOENT,
            # context overflow, sub-agent not found). _handle_step_finish below
            # clears this when a successful step lands after the error, so only
            # an error followed by no further step_finish stays terminal.
            self.terminal_error = f"opencode {name}: {msg}"
            logger.error(f"[Opencode Error] {msg}")

    def _handle_tool_use(self, part: dict[str, Any]) -> None:
        state = part.get("state") or {}
        status = state.get("status")
        if status not in ("completed", "error"):
            return
        call_id = part.get("callID") or part.get("id") or ""
        name = part.get("tool", "unknown")
        args = state.get("input") or {}
        output = (
            state.get("output") if status == "completed" else state.get("error", "")
        )
        truncated = bool((state.get("metadata") or {}).get("truncated"))

        self._turn_tool_calls.append(
            {
                "tool_call_id": call_id,
                "name": name,
                "arguments": args,
            }
        )
        self._turn_observations.append(
            {
                "tool_call_id": call_id,
                "type": "tool_result",
                "content": output or "",
                "truncated": truncated,
            }
        )
        args_json = json.dumps(args)
        logger.info(f"[Opencode Tool] {name} input={args_json}")
        agent_logger.info("tool_use name=%s input=%s", name, args_json)
        agent_logger.info("tool_result content=%s", output or "")

    def _handle_step_finish(self, part: dict[str, Any]) -> None:
        # Clear any prior `error` event — a step landing AFTER an error means
        # opencode (or the agent) recovered. If error was the last word before
        # exit, no step_finish follows and terminal_error stays.
        self.terminal_error = None

        tokens = part.get("tokens") or {}
        self._accumulate_token_usage(tokens, _USAGE_FIELD_MAP)
        self._accumulate_token_usage(tokens.get("cache") or {}, _CACHE_FIELD_MAP)

        # Skip cost=0: OAuth/ChatGPT-sub runs report 0 per step; honoring
        # those would set cost_source="agent" with $0 and the harness loses
        # the chance to derive from token_totals * token_pricing.json.
        cost = part.get("cost")
        if isinstance(cost, (int, float)) and cost > 0:
            self.agent_reported_cost = (self.agent_reported_cost or 0.0) + float(cost)

        reason = part.get("reason")
        if isinstance(reason, str):
            self.stop_reason = reason

        self._flush_turn()
