"""Claude-code event parser. Subclasses ``BaseEventParser``; the only thing
claude-specific is ``_handle_event``, which maps claude's ``--output-format
stream-json`` vocabulary onto the base accumulators.

Claude 2.1.x event types we handle (verified against a real captured stream):

    system/init           — carries session_id
    assistant             — message.content[] with sub-types text / thinking / tool_use
    user                  — message.content[] with tool_result; ends a turn
    stream_event          — when claude is invoked with --include-partial-messages,
                            sub-events fire per turn before the terminal result.
                            We read `event.type == "message_delta"`, which carries
                            the final per-turn usage + stop_reason. Survives SIGTERM.
    result/success        — terminal: num_turns, total_cost_usd, usage (cumulative
                            token totals), stop_reason, duration_api_ms, ttft_ms.
                            Overrides per-turn accumulator when present.
    result/error          — terminal failure path
"""

from __future__ import annotations

import json
from typing import Any

from agent.in_container.event_parser import BaseEventParser
from utils.logger import agent_logger, logger

# Claude's `result.usage` field names → our canonical token_totals names.
_USAGE_FIELD_MAP = {
    "input_tokens": "input_tokens",
    "output_tokens": "output_tokens",
    "cache_read_input_tokens": "cached_input_tokens",
    "cache_creation_input_tokens": "cache_creation_tokens",
}
_USAGE_TTL_MAP = {
    "ephemeral_5m_input_tokens": "cache_creation_tokens_5m",
    "ephemeral_1h_input_tokens": "cache_creation_tokens_1h",
}


class ClaudeCodeEventParser(BaseEventParser):
    """Stateful consumer of claude's ``stream-json`` output."""

    raw_log_prefix = "ClaudeCode"

    def _handle_event(self, data: dict[str, Any]) -> None:
        event_type = data.get("type")

        if event_type == "system":
            if data.get("subtype") == "init":
                sid = data.get("session_id")
                if isinstance(sid, str):
                    self.session_id = sid
                    logger.info(f"[ClaudeCode] Session started: {sid}")

        elif event_type == "assistant":
            for part in data.get("message", {}).get("content", []):
                self._handle_assistant_part(part)

        elif event_type == "user":
            for part in data.get("message", {}).get("content", []):
                if part.get("type") == "tool_result":
                    self._handle_tool_result(part)
            # A user event (tool_result) marks the end of a turn.
            self._flush_turn()

        elif event_type == "stream_event":
            self._handle_stream_event(data.get("event") or {})

        elif event_type == "result":
            self._handle_result(data)

    def _handle_assistant_part(self, part: dict[str, Any]) -> None:
        ptype = part.get("type")
        if ptype == "text":
            text = part.get("text", "")
            if text:
                self._turn_text.append(text)
                logger.info(f"[ClaudeCode Message] {text}")
        elif ptype == "thinking":
            thinking = part.get("thinking", "")
            if thinking:
                self._turn_reasoning.append(thinking)
        elif ptype == "tool_use":
            name = part.get("name", "unknown")
            args = part.get("input", {})
            call_id = part.get("id", "")
            self._turn_tool_calls.append(
                {
                    "tool_call_id": call_id,
                    "name": name,
                    "arguments": args,
                }
            )
            args_json = json.dumps(args)
            logger.info(f"[ClaudeCode Tool] {name} input={args_json}")
            agent_logger.info("tool_use name=%s input=%s", name, args_json)

    def _handle_tool_result(self, part: dict[str, Any]) -> None:
        raw = part.get("content", "")
        if isinstance(raw, list):
            body = "\n".join(b.get("text", str(b)) for b in raw)
        else:
            body = raw
        self._turn_observations.append(
            {
                "tool_call_id": part.get("tool_use_id", ""),
                "type": "tool_result",
                "content": body,
                "truncated": False,
            }
        )
        agent_logger.info("tool_result content=%s", body)

    def _handle_stream_event(self, event: dict[str, Any]) -> None:
        # message_delta carries the FINAL per-turn usage + stop_reason and
        # lands before the terminal result event. Accumulate so totals survive
        # a SIGTERM that kills the CLI before result/success fires.
        if event.get("type") != "message_delta":
            return
        self._record_usage(event.get("usage") or {}, additive=True)
        sr = (event.get("delta") or {}).get("stop_reason")
        if isinstance(sr, str):
            self.stop_reason = sr

    def _handle_result(self, data: dict[str, Any]) -> None:
        # Flush any in-flight turn so its text isn't dropped on assistant-final-text runs.
        self._flush_turn()

        self.agent_reported_turns = data.get("num_turns")
        cost = data.get("total_cost_usd")
        if cost is not None:
            self.agent_reported_cost = float(cost)
        sr = data.get("stop_reason")
        if isinstance(sr, str):
            self.stop_reason = sr

        # Timing (claude is the only CLI that emits these today).
        for src, dst in (("duration_api_ms", "api_ms"), ("ttft_ms", "ttft_ms")):
            val = data.get(src)
            if isinstance(val, int):
                self.timing[dst] = val

        # result.usage is cumulative; wipe any per-turn accumulator first so
        # it becomes the source of truth on success.
        self.token_usage.clear()
        self._record_usage(data.get("usage") or {})

        if data.get("subtype") == "success":
            cost_str = f"${cost:.4f}" if isinstance(cost, (int, float)) else "N/A"
            logger.info(
                f"[ClaudeCode] Completed: {self.agent_reported_turns} turns, cost={cost_str}"
            )
        elif data.get("subtype") == "error":
            logger.error(f"[ClaudeCode] Error: {data.get('error')}")

    def _record_usage(self, usage: dict[str, Any], *, additive: bool = False) -> None:
        """Project claude's ``usage`` blob onto v2 canonical token_totals.

        ``additive=True`` for per-turn message_delta (sum across turns);
        default replace semantics for cumulative result.usage.
        """
        if not usage:
            return

        def _set(dst: str, val: int) -> None:
            self.token_usage[dst] = (
                self.token_usage.get(dst, 0) + val if additive else val
            )

        for src, dst in _USAGE_FIELD_MAP.items():
            val = usage.get(src, 0) or 0
            if val:
                _set(dst, int(val))

        cache_creation = usage.get("cache_creation") or {}
        for src, dst in _USAGE_TTL_MAP.items():
            val = cache_creation.get(src, 0) or 0
            if val:
                _set(dst, int(val))

        # Contract requires input/output keys to be present.
        self.token_usage.setdefault("input_tokens", 0)
        self.token_usage.setdefault("output_tokens", 0)
