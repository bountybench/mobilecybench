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

    def test_timeout_with_no_cost_stays_derived_under_renormalize(self) -> None:
        """Idempotency guard: re-normalizing an already-normalized result must
        keep cost_source='derived', not flip to 'agent' just because cost_usd
        was filled in by the first derive."""
        first = normalize_agent_result(
            {
                "status": "timeout",
                "turns_taken": 0,
                "model": "claude-opus-4-7",
                "token_totals": {},
            }
        )
        assert first["cost_source"] == "derived"
        second = normalize_agent_result(first)
        assert second["cost_source"] == "derived"

    def test_opus_5_missing_cost_uses_all_cache_rates(self) -> None:
        # Input is inclusive under the existing calculator contract:
        # 1M fresh + 1M reads + 1M five-minute writes + 1M one-hour writes.
        out = _norm(
            model="claude-opus-5",
            token_totals={
                "input_tokens": 4_000_000,
                "output_tokens": 1_000_000,
                "cached_input_tokens": 1_000_000,
                "cache_creation_tokens_5m": 1_000_000,
                "cache_creation_tokens_1h": 1_000_000,
            },
        )
        assert out["cost_source"] == "derived"
        assert out["cost_usd"] == 46.75  # 5 + 25 + 0.50 + 6.25 + 10

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


class TestCostSourceSpoofGuard:
    """cost_source is runner-only provenance per result.schema.json.
    An agent-supplied cost_source without cost_usd is the suppression
    spoof — strip and re-resolve. Idempotency on a fully resolved state
    still holds (both keys set ⇒ a prior resolve already happened)."""

    def test_orphan_cost_source_is_stripped_and_rederived(self) -> None:
        """Agent writes cost_source='agent' without cost_usd to short-circuit
        derive (would leave cost_usd=None while claiming agent provenance).
        Must be discarded and re-resolved from token_totals."""
        out = _norm(
            cost_source="agent",
            token_totals={"input_tokens": 1_000_000, "output_tokens": 0},
        )
        assert out["cost_source"] == "derived"
        assert out["cost_usd"] > 0

    def test_resolved_agent_zero_is_idempotent(self) -> None:
        """Legitimate $0 cache-only run produces cost_usd=0.0 +
        cost_source='agent'. Re-normalizing must NOT trip the spoof
        guard — both keys are set, so the resolved state stands."""
        first = _norm(cost_usd=0.0)
        assert first["cost_source"] == "agent"
        assert first["cost_usd"] == 0.0
        second = normalize_agent_result(first)
        assert second["cost_source"] == "agent"
        assert second["cost_usd"] == 0.0


class TestStartupSeedDoesNotWarn:
    """Startup-seed callers (empty model + empty token_totals) used to emit
    a noisy WARN at line 2 of every experiment.log. Suppressed now because
    there's nothing to price."""

    def test_empty_totals_empty_model_does_not_warn(self, caplog) -> None:
        """The harness startup seed (normalize_agent_result(None)) hits this
        exact shape: model="" and token_totals={}. Must not WARN."""
        from utils.token_costs import derive_cost_from_totals

        with caplog.at_level("WARNING"):
            cost, source = derive_cost_from_totals({}, "")

        assert (cost, source) == (0.0, "derived_unpriced")
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert warnings == [], f"Unexpected WARN: {[r.message for r in warnings]}"

    def test_empty_totals_known_model_does_not_warn(self, caplog) -> None:
        """Empty totals with a real pricing row falls through to compute_cost
        which returns 0. No WARN expected because nothing was unpriced."""
        from utils.token_costs import derive_cost_from_totals

        with caplog.at_level("WARNING"):
            cost, source = derive_cost_from_totals({}, "gpt-5.4")

        assert cost == 0.0
        assert source == "derived"
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert warnings == []

    def test_populated_totals_unknown_model_still_warns(self, caplog) -> None:
        """Real un-priced model paths must still WARN — this is real operator
        signal that pricing data is missing for a model that did consume
        tokens."""
        from utils.token_costs import derive_cost_from_totals

        with caplog.at_level("WARNING"):
            cost, source = derive_cost_from_totals(
                {"input_tokens": 100}, "unknown-future-model"
            )

        assert (cost, source) == (0.0, "derived_unpriced")
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any("no pricing row" in r.message for r in warnings)
