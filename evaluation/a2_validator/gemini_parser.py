"""Gemini CLI `--output-format stream-json` parser (the harness has none).

Maps Gemini CLI events onto the shared BaseEventParser accumulators so the
Validator records the same summary fields for all three CLIs. Gemini reports
token counts but no cost; cost is derived from utils/token_pricing.json.

Events handled: init (session_id), message (assistant text, possibly as
deltas), tool_use, tool_result, result (stats with token totals), error.
"""

from __future__ import annotations

from typing import Any

from agent.in_container.event_parser import BaseEventParser

_STATS_MAP = {
    "input_tokens": "input_tokens",
    "input": "input_tokens",
    "output_tokens": "output_tokens",
    "candidates": "output_tokens",
    "cached": "cached_input_tokens",
    "cached_tokens": "cached_input_tokens",
    "thoughts": "reasoning_tokens",
    "thoughts_tokens": "reasoning_tokens",
}


class GeminiEventParser(BaseEventParser):
    raw_log_prefix = "Gemini"

    def _handle_event(self, data: dict[str, Any]) -> None:
        t = data.get("type")
        if t == "init":
            self.session_id = data.get("session_id") or self.session_id
        elif t == "message" and data.get("role") == "assistant":
            text = data.get("content") or ""
            if data.get("delta") and self._turn_text:
                self._turn_text[-1] += text  # deltas extend the current message
            elif text:
                self._turn_text.append(text)
        elif t == "tool_use":
            self._turn_tool_calls.append(
                {
                    "tool_call_id": data.get("tool_id", ""),
                    "name": data.get("tool_name", "unknown"),
                    "arguments": data.get("parameters", {}),
                }
            )
        elif t == "tool_result":
            self._turn_observations.append(
                {
                    "tool_call_id": data.get("tool_id", ""),
                    "type": "tool_result",
                    "content": str(data.get("output", "")),
                    "truncated": False,
                }
            )
            self._flush_turn()
        elif t == "result":
            self._flush_turn()
            stats = data.get("stats") or {}
            self.token_usage.clear()
            self._accumulate_token_usage(
                {k: v for k, v in stats.items() if isinstance(v, int)}, _STATS_MAP
            )
            if data.get("status") not in (None, "success"):
                self.terminal_error = (
                    f"gemini: {data.get('error') or data.get('status')}"
                )
        elif t == "error":
            self.terminal_error = f"gemini: {data.get('message') or data}"
