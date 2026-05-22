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
from agent.opencode import run_in_container as opencode_runner
from agent.opencode.event_parser import OpencodeEventParser

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

    def test_claude_message_delta_survives_timeout(self) -> None:
        """When the terminal result event never lands (SIGTERM mid-run), per-turn
        message_delta events keep token totals + stop_reason intact. Gated on
        the --include-partial-messages CLI flag in run_in_container.py."""
        parser = ClaudeCodeEventParser()
        for usage in (
            {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 20},
            {"input_tokens": 200, "output_tokens": 80, "cache_read_input_tokens": 40},
        ):
            parser.feed_chunk(
                json.dumps(
                    {
                        "type": "stream_event",
                        "event": {
                            "type": "message_delta",
                            "delta": {"stop_reason": "end_turn"},
                            "usage": usage,
                        },
                    }
                )
                + "\n"
            )
        summary = parser.summarize({}, exit_code=143, elapsed=1.0)
        assert summary["status"] == "error"  # SIGTERM exit code
        assert summary["token_totals"]["input_tokens"] == 300
        assert summary["token_totals"]["output_tokens"] == 130
        assert summary["token_totals"]["cached_input_tokens"] == 60
        assert summary["stop_reason"] == "end_turn"

    def test_claude_result_overrides_per_turn_accumulator(self) -> None:
        """On success, the cumulative result.usage replaces any per-turn sum
        (else we'd double-count once result fires after message_deltas)."""
        parser = ClaudeCodeEventParser()
        parser.feed_chunk(
            json.dumps(
                {
                    "type": "stream_event",
                    "event": {
                        "type": "message_delta",
                        "delta": {"stop_reason": "end_turn"},
                        "usage": {"input_tokens": 100, "output_tokens": 50},
                    },
                }
            )
            + "\n"
        )
        parser.feed_chunk(
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "num_turns": 1,
                    "total_cost_usd": 0.01,
                    "usage": {"input_tokens": 100, "output_tokens": 50},
                }
            )
            + "\n"
        )
        totals = parser.summarize({}, 0, 0.0)["token_totals"]
        assert totals["input_tokens"] == 100  # not 200
        assert totals["output_tokens"] == 50  # not 100

    def test_claude_captures_agent_cost_and_turns(self) -> None:
        """result event → agent_reported_cost + agent_reported_turns."""
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


class TestTerminalError:
    """Parser-driven status override when a CLI signals failure without a
    nonzero exit (opencode auth failure, claude result/error)."""

    def test_opencode_terminal_error_forces_status_error_on_exit_zero(self) -> None:
        parser = OpencodeEventParser()
        parser.feed_chunk(
            json.dumps(
                {
                    "type": "error",
                    "error": {
                        "name": "ProviderAuthError",
                        "data": {"message": "API key missing"},
                    },
                }
            )
            + "\n"
        )
        summary = parser.summarize(_TASK, exit_code=0, elapsed=1.0)
        assert summary["status"] == "error"
        assert "ProviderAuthError" in summary["error_traceback"]
        assert "API key missing" in summary["error_traceback"]

    def test_opencode_recovery_clears_terminal_error(self) -> None:
        # opencode also emits `error` for recoverable mid-run failures; a
        # step_finish landing after proves recovery and must clear.
        parser = OpencodeEventParser()
        parser.feed_chunk(
            json.dumps(
                {
                    "type": "error",
                    "error": {"name": "Unknown", "data": {"message": "ENOENT"}},
                }
            )
            + "\n"
        )
        assert parser.terminal_error is not None
        parser.feed_chunk(_opencode_step_finish(input_t=1, output_t=1))
        assert parser.terminal_error is None
        assert (
            parser.summarize(_TASK, exit_code=0, elapsed=1.0)["status"] == "completed"
        )

    def test_opencode_string_error_payload_does_not_crash(self) -> None:
        parser = OpencodeEventParser()
        parser.feed_chunk(
            json.dumps({"type": "error", "error": "flat string error"}) + "\n"
        )
        assert parser.terminal_error is not None
        assert "flat string error" in parser.terminal_error

    def test_codex_turn_failed_is_terminal(self) -> None:
        parser = CodexEventParser()
        parser.feed_chunk(
            json.dumps(
                {
                    "type": "turn.failed",
                    "error": {"message": "model rejected the tool call"},
                }
            )
            + "\n"
        )
        assert parser.terminal_error is not None
        assert "model rejected" in parser.terminal_error

    def test_codex_top_level_error_is_not_terminal(self) -> None:
        # Codex may stash a top-level error then recover via a later
        # turn.completed; only turn.failed is terminal.
        parser = CodexEventParser()
        parser.feed_chunk(
            json.dumps({"type": "error", "message": "transient API blip"}) + "\n"
        )
        assert parser.terminal_error is None

    def test_claude_result_error_is_terminal(self) -> None:
        parser = ClaudeCodeEventParser()
        parser.feed_chunk(
            json.dumps(
                {"type": "result", "subtype": "error", "error": "rate limit exceeded"}
            )
            + "\n"
        )
        assert parser.terminal_error is not None
        assert "rate limit" in parser.terminal_error


def _opencode_step_finish(
    *, input_t: int, output_t: int, cache_read: int = 0, cost: float = 0.0
) -> str:
    return (
        json.dumps(
            {
                "type": "step_finish",
                "part": {
                    "type": "step-finish",
                    "reason": "stop",
                    "tokens": {
                        "input": input_t,
                        "output": output_t,
                        "reasoning": 0,
                        "cache": {"read": cache_read, "write": 0},
                    },
                    "cost": cost,
                },
            }
        )
        + "\n"
    )


class TestOpencodeParser:
    """OpencodeEventParser invariants the BYO contract depends on."""

    def test_step_finish_tokens_are_per_step_and_sum(self) -> None:
        # opencode emits per-step (not cumulative) usage; parser must sum.
        parser = OpencodeEventParser()
        parser.feed_chunk(_opencode_step_finish(input_t=800, output_t=40))
        parser.feed_chunk(
            _opencode_step_finish(input_t=400, output_t=40, cache_read=200)
        )
        parser.feed_chunk(
            _opencode_step_finish(input_t=500, output_t=5, cache_read=200)
        )
        totals = parser.summarize(_TASK, 0, 0.0)["token_totals"]
        assert totals["input_tokens"] == 1700
        assert totals["output_tokens"] == 85
        assert totals["cached_input_tokens"] == 400

    @pytest.mark.parametrize(
        "case,costs,expected_cost_usd",
        [
            # OAuth runs: every step reports 0 → omit cost so harness derives from totals.
            ("all_zero_defers_to_derived", [0.0, 0.0], None),
            # API-key runs: any non-zero step → trust the agent's sum.
            ("any_nonzero_reported", [0.001, 0.002], 0.003),
            ("mixed_zero_nonzero", [0.0, 0.005], 0.005),
        ],
        ids=lambda v: v if isinstance(v, str) else "",
    )
    def test_cost_aggregation(
        self, case: str, costs: list, expected_cost_usd: float | None
    ) -> None:
        parser = OpencodeEventParser()
        for c in costs:
            parser.feed_chunk(_opencode_step_finish(input_t=10, output_t=5, cost=c))
        summary = parser.summarize(_TASK, 0, 0.0)
        if expected_cost_usd is None:
            assert "cost_usd" not in summary
        else:
            assert summary["cost_usd"] == pytest.approx(expected_cost_usd)

    def test_tool_use_normalizes_to_byo_shape(self) -> None:
        parser = OpencodeEventParser()
        parser.feed_chunk(
            json.dumps(
                {
                    "type": "step_start",
                    "sessionID": "ses_abc",
                    "part": {"type": "step-start"},
                }
            )
            + "\n"
        )
        parser.feed_chunk(
            json.dumps(
                {
                    "type": "tool_use",
                    "part": {
                        "type": "tool",
                        "tool": "bash",
                        "callID": "call_xyz",
                        "state": {
                            "status": "completed",
                            "input": {"command": "echo hi"},
                            "output": "hi\n",
                            "metadata": {"truncated": False},
                        },
                    },
                }
            )
            + "\n"
        )
        parser.feed_chunk(_opencode_step_finish(input_t=1, output_t=1))
        rec = parser.drain_records(_TASK)[0]
        assert rec["tool_calls"][0] == {
            "tool_call_id": "call_xyz",
            "name": "bash",
            "arguments": {"command": "echo hi"},
        }
        assert rec["observations"][0]["content"] == "hi\n"
        assert parser.summarize({}, 0, 0.0)["session_id"] == "ses_abc"

    def test_empty_run_produces_valid_summary_shape(self) -> None:
        # SIGTERM before any step finishes — summary must still be valid.
        parser = OpencodeEventParser()
        result = parser.summarize(_TASK, exit_code=143, elapsed=0.5)
        assert result["status"] == "error"
        assert result["turns_taken"] == 0
        assert result["token_totals"] == {}


_AUTH_VARS = (
    "OPENCODE_OPENAI_AUTH",
    "OPENCODE_AUTH_CONTENT",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_GENERATIVE_AI_API_KEY",
)


@pytest.fixture
def clean_auth_env(monkeypatch: pytest.MonkeyPatch):
    """Clear every auth var the opencode runner touches; return os.environ."""
    import os

    for k in _AUTH_VARS:
        monkeypatch.delenv(k, raising=False)
        os.environ.pop(k, None)
    return os.environ


class TestOpenAIAuthMode:
    """OPENCODE_OPENAI_AUTH: experimental, OpenAI-only auth-source toggle.

    Strips the inactive OpenAI credential so opencode cannot silently swap
    mid-run. Never touches non-OpenAI provider keys.
    """

    @pytest.mark.parametrize(
        "case,setup,stripped,kept",
        [
            # oauth: strip API key.
            (
                "oauth",
                {
                    "OPENCODE_OPENAI_AUTH": "oauth",
                    "OPENCODE_AUTH_CONTENT": "x",
                    "OPENAI_API_KEY": "k",
                    "ANTHROPIC_API_KEY": "a",
                },
                ("OPENAI_API_KEY",),
                {"OPENCODE_AUTH_CONTENT": "x", "ANTHROPIC_API_KEY": "a"},
            ),
            # apikey: strip OAuth blob.
            (
                "apikey",
                {
                    "OPENCODE_OPENAI_AUTH": "apikey",
                    "OPENCODE_AUTH_CONTENT": "x",
                    "OPENAI_API_KEY": "k",
                },
                ("OPENCODE_AUTH_CONTENT",),
                {"OPENAI_API_KEY": "k"},
            ),
            # auto + only API key: keep.
            ("auto_apikey_only", {"OPENAI_API_KEY": "k"}, (), {"OPENAI_API_KEY": "k"}),
            # auto + usable OAuth: strip API key.
            (
                "auto_prefers_usable_oauth",
                {
                    "OPENCODE_AUTH_CONTENT": '{"openai":{"type":"oauth"}}',
                    "OPENAI_API_KEY": "k",
                },
                ("OPENAI_API_KEY",),
                {"OPENCODE_AUTH_CONTENT": '{"openai":{"type":"oauth"}}'},
            ),
            # auto + malformed blob: keep API key.
            (
                "auto_malformed_blob_keeps_api_key",
                {"OPENCODE_AUTH_CONTENT": "not-json", "OPENAI_API_KEY": "k"},
                (),
                {"OPENAI_API_KEY": "k"},
            ),
            # auto + blob without openai entry: keep API key.
            (
                "auto_blob_without_openai_keeps_api_key",
                {
                    "OPENCODE_AUTH_CONTENT": '{"anthropic":{"type":"api"}}',
                    "OPENAI_API_KEY": "k",
                },
                (),
                {"OPENAI_API_KEY": "k"},
            ),
            # Non-OpenAI creds never touched.
            (
                "non_openai_passthrough",
                {"ANTHROPIC_API_KEY": "a"},
                (),
                {"ANTHROPIC_API_KEY": "a"},
            ),
        ],
        ids=lambda v: v if isinstance(v, str) else "",
    )
    def test_apply_openai_auth_mode(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_auth_env,
        case: str,
        setup: dict,
        stripped: tuple,
        kept: dict,
    ) -> None:
        for k, v in setup.items():
            monkeypatch.setenv(k, v)

        opencode_runner._apply_openai_auth_mode()

        for k in stripped:
            assert k not in clean_auth_env, f"[{case}] expected {k} stripped"
        for k, v in kept.items():
            assert clean_auth_env.get(k) == v, f"[{case}] expected {k}={v}"

    def test_unknown_mode_warns_and_falls_back_to_auto(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_auth_env,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # OpenAI-only setting; a typo must not abort non-OpenAI runs.
        monkeypatch.setenv("OPENCODE_OPENAI_AUTH", "potato")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        with caplog.at_level("WARNING"):
            opencode_runner._apply_openai_auth_mode()
        assert clean_auth_env.get("OPENAI_API_KEY") == "k"
        assert clean_auth_env.get("ANTHROPIC_API_KEY") == "a"
        assert any("potato" in r.message for r in caplog.records)


class TestNormalizeProviderEnv:
    """_normalize_provider_env: operator env names -> opencode SDK names.

    GEMINI_API_KEY → GOOGLE_GENERATIVE_AI_API_KEY (what opencode's Google
    SDK reads). Mirror only when target is unset, so explicit operator
    override always wins.
    """

    @pytest.mark.parametrize(
        "case,initial,expected",
        [
            (
                "alias_mirrored",
                {"GEMINI_API_KEY": "g"},
                {"GEMINI_API_KEY": "g", "GOOGLE_GENERATIVE_AI_API_KEY": "g"},
            ),
            ("no_source_no_target", {}, {"GOOGLE_GENERATIVE_AI_API_KEY": None}),
            (
                "explicit_target_wins",
                {"GEMINI_API_KEY": "g", "GOOGLE_GENERATIVE_AI_API_KEY": "explicit"},
                {"GOOGLE_GENERATIVE_AI_API_KEY": "explicit"},
            ),
        ],
        ids=lambda v: v if isinstance(v, str) else "",
    )
    def test_normalize_provider_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_auth_env,
        case: str,
        initial: dict,
        expected: dict,
    ) -> None:
        for k, v in initial.items():
            monkeypatch.setenv(k, v)

        opencode_runner._normalize_provider_env()

        for k, v in expected.items():
            if v is None:
                assert k not in clean_auth_env, f"[{case}] expected {k} unset"
            else:
                assert clean_auth_env.get(k) == v, f"[{case}] expected {k}={v}"
