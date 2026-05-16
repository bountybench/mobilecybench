"""Behavior tests for the CLI event parsers.

Focused on the public contract: drain_records returns pending conversation
events once (incremental writes survive mid-run crash), summarize produces
schema-conformant result.json shape, and feed_chunk/flush handle realistic
stream fragments.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from agent.claude_code.event_parser import ClaudeCodeEventParser
from agent.codex.event_parser import CodexEventParser

_TASK: dict[str, Any] = {"run_id": "lab-run-001", "model": "test-model"}


@pytest.fixture(scope="module")
def conversation_validator() -> jsonschema.Draft202012Validator:
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "schemas"
        / "conversation_turn.schema.json"
    )
    if not schema_path.exists():
        pytest.skip("conversation_turn schema not present")
    with schema_path.open(encoding="utf-8") as f:
        return jsonschema.Draft202012Validator(json.load(f))


class TestDrainRecords:
    """drain_records must hand each event out exactly once."""

    def test_codex_empty_parser_drains_nothing(self) -> None:
        assert CodexEventParser().drain_records(_TASK) == []

    def test_claude_empty_parser_drains_nothing(self) -> None:
        assert ClaudeCodeEventParser().drain_records(_TASK) == []

    def test_codex_drain_is_idempotent(self) -> None:
        parser = CodexEventParser()
        # Feed one complete turn end-to-end so a conversation event flushes.
        parser.feed_chunk(json.dumps({"type": "turn.started"}) + "\n")
        parser.feed_chunk(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "hello"},
                }
            )
            + "\n"
        )
        parser.feed_chunk(json.dumps({"type": "turn.completed", "usage": {}}) + "\n")

        first = parser.drain_records(_TASK)
        second = parser.drain_records(_TASK)
        assert len(first) == 1
        assert second == []  # already drained

    def test_claude_drain_is_idempotent(self) -> None:
        parser = ClaudeCodeEventParser()
        # Claude flushes a turn when a user event lands.
        parser.feed_chunk(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": "hi"}]},
                }
            )
            + "\n"
        )
        parser.feed_chunk(
            json.dumps(
                {
                    "type": "user",
                    "message": {
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "x",
                                "content": "ok",
                            }
                        ]
                    },
                }
            )
            + "\n"
        )

        first = parser.drain_records(_TASK)
        second = parser.drain_records(_TASK)
        assert len(first) == 1
        assert second == []


class TestRecordShape:
    """Drained records carry the BYO contract fields."""

    def test_codex_record_carries_assistant_text_and_run_id(self) -> None:
        parser = CodexEventParser()
        parser.feed_chunk(json.dumps({"type": "turn.started"}) + "\n")
        parser.feed_chunk(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "answer"},
                }
            )
            + "\n"
        )
        parser.feed_chunk(json.dumps({"type": "turn.completed", "usage": {}}) + "\n")

        rec = parser.drain_records(_TASK)[0]
        assert rec["run_id"] == "lab-run-001"
        assert rec["assistant_text"] == "answer"
        assert rec["turn_number"] >= 1
        assert rec["status"] == "ok"

    def test_claude_record_normalizes_observation_shape(self) -> None:
        """tool_use_id → tool_call_id, type/truncated populated."""
        parser = ClaudeCodeEventParser()
        parser.feed_chunk(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "abc",
                                "name": "Bash",
                                "input": {"cmd": "ls"},
                            },
                        ]
                    },
                }
            )
            + "\n"
        )
        parser.feed_chunk(
            json.dumps(
                {
                    "type": "user",
                    "message": {
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "abc",
                                "content": "file1\nfile2",
                            }
                        ]
                    },
                }
            )
            + "\n"
        )

        rec = parser.drain_records(_TASK)[0]
        obs = rec["observations"][0]
        assert obs["tool_call_id"] == "abc"
        assert obs["type"] == "tool_result"
        assert obs["truncated"] is False
        assert obs["content"] == "file1\nfile2"


class TestSummarize:
    """summarize produces the result.json shape both on clean exit and error."""

    def test_codex_summarize_status_from_exit_code(self) -> None:
        parser = CodexEventParser()
        clean = parser.summarize(_TASK, exit_code=0, elapsed=1.0)
        assert clean["status"] == "completed"
        bad = parser.summarize(_TASK, exit_code=137, elapsed=1.0)
        assert bad["status"] == "error"
        assert "error_traceback" in bad

    def test_claude_summarize_with_partial_state(self) -> None:
        """Summarize with no events still returns a valid shape — needed for
        the SIGKILL-mid-run case where the parser has accumulated nothing
        but the runner must still write a result.json snapshot."""
        parser = ClaudeCodeEventParser()
        result = parser.summarize(_TASK, exit_code=143, elapsed=0.5)
        assert result["status"] == "error"
        assert result["turns_taken"] == 0
        assert result["token_totals"] == {}


class TestFeedChunkResilience:
    """Stream fragments split across chunk boundaries must not lose data."""

    def test_codex_handles_split_line(self) -> None:
        parser = CodexEventParser()
        full = json.dumps({"type": "thread.started", "thread_id": "t1"})
        parser.feed_chunk(full[: len(full) // 2])
        parser.feed_chunk(full[len(full) // 2 :] + "\n")
        assert parser.summarize({}, 0, 0.0)["session_id"] == "t1"

    def test_claude_handles_split_line(self) -> None:
        parser = ClaudeCodeEventParser()
        full = json.dumps({"type": "system", "subtype": "init", "session_id": "s1"})
        parser.feed_chunk(full[: len(full) // 2])
        parser.feed_chunk(full[len(full) // 2 :] + "\n")
        assert parser.summarize({}, 0, 0.0)["session_id"] == "s1"

    def test_codex_flush_drains_partial_line(self) -> None:
        """flush() should attempt to parse trailing buffered content."""
        parser = CodexEventParser()
        parser.feed_chunk(
            json.dumps({"type": "thread.started", "thread_id": "t9"})
        )  # no newline
        parser.flush()
        assert parser.summarize({}, 0, 0.0)["session_id"] == "t9"

    def test_codex_captures_reasoning_text(self) -> None:
        """Codex emits reasoning text in item.completed/reasoning; capture it."""
        parser = CodexEventParser()
        parser.feed_chunk(json.dumps({"type": "turn.started"}) + "\n")
        parser.feed_chunk(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "reasoning",
                        "id": "r1",
                        "text": "I should list files first.",
                    },
                }
            )
            + "\n"
        )
        parser.feed_chunk(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "Done"},
                }
            )
            + "\n"
        )
        parser.feed_chunk(json.dumps({"type": "turn.completed", "usage": {}}) + "\n")
        rec = parser.drain_records({"run_id": "r", "model": "m"})[0]
        assert rec["reasoning_summary"] == "I should list files first."

    def test_claude_canonical_cache_field_names(self) -> None:
        """Parser renames claude's usage fields to canonical names."""
        parser = ClaudeCodeEventParser()
        parser.feed_chunk(
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "num_turns": 1,
                    "total_cost_usd": 0.10,
                    "usage": {
                        "input_tokens": 5,
                        "output_tokens": 7,
                        "cache_read_input_tokens": 100,
                        "cache_creation_input_tokens": 200,
                        "cache_creation": {
                            "ephemeral_5m_input_tokens": 0,
                            "ephemeral_1h_input_tokens": 200,
                        },
                    },
                }
            )
            + "\n"
        )
        totals = parser.summarize({}, 0, 0.0)["token_totals"]
        assert totals["cached_input_tokens"] == 100
        assert totals["cache_creation_tokens"] == 200
        assert totals["cache_creation_tokens_1h"] == 200
        assert "cache_read_input_tokens" not in totals
        assert "cache_creation_input_tokens" not in totals

    def test_claude_captures_agent_cost_and_turns(self) -> None:
        """Claude's result event populates agent_reported_cost + agent_reported_turns."""
        parser = ClaudeCodeEventParser()
        parser.feed_chunk(
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "num_turns": 3,
                    "total_cost_usd": 0.2199,
                    "stop_reason": "end_turn",
                    "duration_api_ms": 8000,
                    "ttft_ms": 4500,
                    "usage": {"input_tokens": 1, "output_tokens": 2},
                }
            )
            + "\n"
        )
        summary = parser.summarize({}, 0, 0.0)
        assert summary["cost_usd"] == 0.2199
        assert summary["turns_taken"] == 3
        assert summary["stop_reason"] == "end_turn"
        assert summary["timing"] == {"api_ms": 8000, "ttft_ms": 4500}
