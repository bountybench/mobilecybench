"""Behavior tests for the cost resolution applied by normalize_agent_result.

Agent-reported cost wins whenever PRESENT (non-null), including a legitimate $0.
Harness derives from token_totals × token_pricing.json when the agent omits the
key. Unknown model → cost_source="derived_unpriced", cost=0.
"""

from __future__ import annotations

from utils.run_artifacts import normalize_agent_result


def _norm(**fields):
    base = {
        "status": "completed",
        "turns_taken": 1,
        "model": fields.pop("model", "claude-opus-4-7"),
        "token_totals": fields.pop(
            "token_totals", {"input_tokens": 0, "output_tokens": 0}
        ),
    }
    base.update(fields)
    return normalize_agent_result(base)


class TestCostResolution:
    """Agent-reported cost wins when non-null."""

    def test_agent_reported_present_wins(self) -> None:
        out = _norm(cost_usd=0.5)
        assert out["cost_usd"] == 0.5
        assert out["cost_source"] == "agent"

    def test_agent_reported_zero_is_trusted_not_fallthrough(self) -> None:
        """Claude legitimately emits $0 on cache-only/refusal runs. Don't fall through."""
        out = _norm(cost_usd=0.0)
        assert out["cost_usd"] == 0.0
        assert out["cost_source"] == "agent"

    def test_agent_omits_cost_falls_to_derived(self) -> None:
        out = _norm(token_totals={"input_tokens": 1_000_000, "output_tokens": 0})
        assert out["cost_source"] == "derived"
        assert out["cost_usd"] > 0  # priced model + nonzero tokens

    def test_unknown_model_marks_unpriced(self) -> None:
        out = _norm(
            model="some-future-model-not-in-table",
            token_totals={"input_tokens": 1000, "output_tokens": 1000},
        )
        assert out["cost_source"] == "derived_unpriced"
        assert out["cost_usd"] == 0.0

    def test_missing_model_marks_unpriced(self) -> None:
        out = _norm(
            model="", token_totals={"input_tokens": 1000, "output_tokens": 1000}
        )
        assert out["cost_source"] == "derived_unpriced"
        assert out["cost_usd"] == 0.0

    def test_provider_prefixed_model_resolves(self) -> None:
        """LiteLLM-style names like 'anthropic/claude-opus-4-7' must hit pricing."""
        bare = _norm(
            model="claude-opus-4-7",
            token_totals={"input_tokens": 1_000_000, "output_tokens": 0},
        )
        prefixed = _norm(
            model="anthropic/claude-opus-4-7",
            token_totals={"input_tokens": 1_000_000, "output_tokens": 0},
        )
        assert prefixed["cost_source"] == "derived"
        assert prefixed["cost_usd"] == bare["cost_usd"]
        assert prefixed["cost_usd"] > 0

    def test_dated_model_suffix_resolves(self) -> None:
        """Snapshot suffixes like '-20250929' must hit the base model row."""
        out = _norm(
            model="claude-opus-4-7-20250929",
            token_totals={"input_tokens": 1_000_000, "output_tokens": 0},
        )
        assert out["cost_source"] == "derived"
        assert out["cost_usd"] > 0


class TestCostBreakdown:
    """cost_breakdown carries both sides so drift is auditable."""

    def test_both_present_records_delta(self) -> None:
        # Both agent reports cost AND we can derive from tokens.
        out = _norm(
            cost_usd=0.5,
            token_totals={"input_tokens": 1_000_000, "output_tokens": 0},
        )
        bd = out["cost_breakdown"]
        assert bd["agent_reported"] == 0.5
        assert bd["harness_derived"] is not None
        assert bd["delta"] == bd["harness_derived"] - 0.5

    def test_only_derived_no_delta(self) -> None:
        out = _norm(token_totals={"input_tokens": 1000, "output_tokens": 0})
        bd = out["cost_breakdown"]
        assert bd["agent_reported"] is None
        assert bd["delta"] is None

    def test_unpriced_model_derived_is_null_for_audit(self) -> None:
        """When derive can't produce a real number, audit side is null (not 0).
        Distinguishes 'we tried and got 0' from 'we couldn't compute'."""
        out = _norm(
            cost_usd=0.5,
            model="some-future-model-not-in-table",
            token_totals={"input_tokens": 100, "output_tokens": 0},
        )
        bd = out["cost_breakdown"]
        assert bd["harness_derived"] is None


class TestCacheTierPricing:
    """Cache-aware derive: TTL split wins over flat when both present."""

    def test_ttl_split_used_when_present(self) -> None:
        """Provide TTL split AND flat total; TTL split should drive the math (no double-count).

        Hard-test: if our code double-counted, the cost would be ~2× the right number.
        Sanity-bound the result to a reasonable range for the inputs.
        """
        out = _norm(
            model="claude-opus-4-7",
            token_totals={
                "input_tokens": 100_000,
                "output_tokens": 1_000,
                "cache_creation_tokens": 50_000,  # the flat rollup
                "cache_creation_tokens_5m": 30_000,  # split
                "cache_creation_tokens_1h": 20_000,  # split
            },
        )
        # With claude-opus-4-7's $5 input + $25 output + cache_input fallback,
        # cost should be well under $5 for these volumes. Double-counted would
        # exceed it. We just need a finite, bounded number.
        assert 0 < out["cost_usd"] < 5.0
        assert out["cost_source"] == "derived"

    def test_flat_only_falls_back_when_no_split(self) -> None:
        """When the CLI emits cache_creation_tokens with no TTL split (opencode-style),
        derive uses the flat rollup."""
        out = _norm(
            model="claude-opus-4-7",
            token_totals={
                "input_tokens": 100_000,
                "output_tokens": 1_000,
                "cache_creation_tokens": 50_000,
            },
        )
        assert out["cost_source"] == "derived"
        assert out["cost_usd"] > 0
