"""Tests for run_artifacts timing helpers + merge semantics.

Covers two recent changes:

* ``_timing_summary_from_calls([])`` now returns canonical-keys-with-nulls
  for dispatch paths that bypass ``time_tracker`` (BYO subprocess).
  Previously emitted ``0.0`` / ``0`` for total/llm_call_count, which
  contradicted non-zero ``tool_call_count`` and ``token_totals``.

* ``timing_summary = {**time_tracker_timing, **agent_timing}`` in
  ``write_run_summary`` keeps the canonical 5 keys always present,
  letting agent-supplied CLI-native fields (``api_ms``, ``ttft_ms``)
  overlay on top when populated. Previous conditional fallback emitted
  ``{api_ms: N}``-only on one liveness path and zeros-shape on another.
"""

from types import SimpleNamespace

from utils.run_artifacts import _timing_summary_from_calls

CANONICAL_KEYS = {"total_llm_time", "llm_call_count", "p50", "p95", "max"}


# ---------------------------------------------------------------------------
# Change 1 — _timing_summary_from_calls returns nulls for unmeasured paths.


def test_timing_summary_empty_calls_returns_canonical_nulls():
    summary = _timing_summary_from_calls([])

    assert set(summary.keys()) == CANONICAL_KEYS
    # All five fields must be ``None`` — not ``0`` — so they read as
    # "not measured", not "measured at zero".
    assert all(summary[k] is None for k in CANONICAL_KEYS)


def test_timing_summary_populated_calls_returns_numbers():
    calls = [SimpleNamespace(duration=1.0), SimpleNamespace(duration=3.0)]

    summary = _timing_summary_from_calls(calls)

    assert set(summary.keys()) == CANONICAL_KEYS
    assert summary["total_llm_time"] == 4.0
    assert summary["llm_call_count"] == 2
    assert isinstance(summary["p50"], float)
    assert isinstance(summary["max"], float)


# ---------------------------------------------------------------------------
# Change 2 — canonical-then-overlay merge in write_run_summary keeps the
# canonical 5 keys for every dispatch and lets CLI-native fields overlay.
#
# The merge is one inline line in write_run_summary:
#   timing_summary = {**time_tracker_timing, **agent_timing}
# Tested here via direct dict construction so the assertion is precise
# without standing up the full write_run_summary pipeline.


def _merge(time_tracker_timing, agent_timing):
    return {**time_tracker_timing, **agent_timing}


def test_merge_byo_no_agent_timing_yields_canonical_nulls():
    tt = _timing_summary_from_calls([])
    merged = _merge(tt, {})

    assert set(merged.keys()) == CANONICAL_KEYS
    assert all(merged[k] is None for k in CANONICAL_KEYS)


def test_merge_byo_with_api_ms_overlays_on_canonical_nulls():
    tt = _timing_summary_from_calls([])
    merged = _merge(tt, {"api_ms": 6829, "ttft_ms": 142})

    assert CANONICAL_KEYS <= set(merged.keys())
    assert merged["api_ms"] == 6829
    assert merged["ttft_ms"] == 142
    # Canonical keys still null because time_tracker had no calls.
    assert merged["total_llm_time"] is None
    assert merged["llm_call_count"] is None


def test_merge_custom_path_keeps_time_tracker_numbers():
    calls = [SimpleNamespace(duration=2.5)]
    tt = _timing_summary_from_calls(calls)
    merged = _merge(tt, {})

    assert merged["total_llm_time"] == 2.5
    assert merged["llm_call_count"] == 1


def test_merge_passes_through_unexpected_agent_keys():
    """Agents may emit fields the harness doesn't know about. The merge
    must let them through without dropping the canonical 5."""
    tt = _timing_summary_from_calls([])
    merged = _merge(tt, {"unknown_field": 1, "api_ms": 100})

    assert CANONICAL_KEYS <= set(merged.keys())
    assert merged["unknown_field"] == 1
    assert merged["api_ms"] == 100
