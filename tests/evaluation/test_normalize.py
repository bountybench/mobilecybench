"""Tests for `evaluation.analysis.normalize`."""

from __future__ import annotations

from evaluation.analysis import normalize
from tests.evaluation.conftest import make_summary


def test_normalize_token_totals_custom():
    summary = make_summary(run_id="x")
    out = normalize.normalize_token_totals(summary)
    assert out["input_tokens"] == 1234
    assert out["output_tokens"] == 567
    assert out["reasoning_tokens"] == 89
    assert out["cache_read_tokens"] == 10
    assert out["cache_creation_tokens"] is None
    assert out["cost_usd"] == 0.12


def test_normalize_token_totals_claude_code():
    summary = make_summary(
        run_id="x",
        agent_type="claude-code",
        token_totals={
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_creation_input_tokens": 20,
            "cache_read_input_tokens": 30,
            "cost_usd": 0.05,
            "per_model": {"claude-sonnet-4-6": {}},
        },
    )
    out = normalize.normalize_token_totals(summary)
    assert out["cache_read_tokens"] == 30
    assert out["cache_creation_tokens"] == 20
    assert out["reasoning_tokens"] is None
    assert out["calls"] == 1


def test_normalize_token_totals_codex():
    summary = make_summary(
        run_id="x",
        agent_type="codex",
        token_totals={
            "input_tokens": 100,
            "output_tokens": 50,
            "reasoning_output_tokens": 10,
            "cached_input_tokens": 25,
        },
    )
    out = normalize.normalize_token_totals(summary)
    assert out["reasoning_tokens"] == 10
    assert out["cache_read_tokens"] == 25
    assert out["cache_creation_tokens"] is None
    assert out["cost_usd"] is None


def test_csv_encode_round_trip():
    assert normalize.csv_encode(None) == ""
    assert normalize.csv_encode(True) == "true"
    assert normalize.csv_encode([1, 2]) == "[1, 2]"
    assert normalize.csv_encode({"b": 2, "a": 1}) == '{"a": 1, "b": 2}'


def test_is_pass():
    assert normalize.is_pass(make_summary(run_id="a", score=1)) is True
    assert normalize.is_pass(make_summary(run_id="a", score=1.0)) is True
    assert normalize.is_pass(make_summary(run_id="a", score=0)) is False
    assert normalize.is_pass(make_summary(run_id="a", score=None)) is False
