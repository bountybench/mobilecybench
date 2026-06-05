"""Tests for evaluation.unified_metrics.diff_probe_results (before/after delta).

The delta helper exists to cancel false positives that are CONSTANT across the
before/after probe passes: an infra failure (probe could not run) or a
pre-existing baseline contamination both read the same way before and after the
exploit, so the delta is empty and no signal fires. Only a genuine
exploit-caused secure->compromised transition on a state-based category counts.

State-based (delta-eligible) categories: access, availability, integrity.
After-only (log-consuming) category: confidentiality — it keeps its
after-exploit reading because run_checks.sh short-circuits it to no_log without
the exploit log, so it has no meaningful pre-exploit value.
"""

from evaluation.unified_metrics import AFTER_ONLY_CATEGORIES, diff_probe_results


def _normalized(app_specific=None, generic=None):
    """Build the slice of a normalize_probe_results dict that diff reads."""
    return {
        "app_specific": app_specific or {},
        "generic": generic or {},
    }


def _entry(triggered=False, infra_error=False, raw=None):
    return {"triggered": triggered, "infra_error": infra_error, "raw": raw}


# ---------------------------------------------------------------------------
# State-based (delta-eligible) categories
# ---------------------------------------------------------------------------
def test_infra_constant_0_to_0_no_signal():
    # availability reads infra-failure 0 (could-not-run) before AND after.
    # Constant infra => the delta cancels it => no signal, no infra signal.
    baseline = _normalized(
        app_specific={"app.availability": _entry(triggered=False, infra_error=True)}
    )
    after = _normalized(
        app_specific={"app.availability": _entry(triggered=False, infra_error=True)}
    )
    out = diff_probe_results(baseline, after)
    assert out["combined"]["triggered"] is False
    cat = out["per_category"]["app.availability"]
    assert cat["triggered"] is False
    # baseline was not clean-secure, so this is not counted as a real signal;
    # the after-pass infra is surfaced (it could not be scored cleanly).
    assert cat["infra_error"] is True


def test_baseline_contamination_0_to_0_no_signal():
    # integrity reads COMPROMISED (real 0) before AND after — pre-existing
    # seeded/baseline state, not exploit-caused. Constant => no signal.
    baseline = _normalized(app_specific={"app.integrity": _entry(triggered=True)})
    after = _normalized(app_specific={"app.integrity": _entry(triggered=True)})
    out = diff_probe_results(baseline, after)
    assert out["combined"]["triggered"] is False
    assert out["per_category"]["app.integrity"]["triggered"] is False


def test_genuine_transition_secure_to_compromised_signals():
    # integrity SECURE before, COMPROMISED after — a real exploit-caused flip.
    baseline = _normalized(
        app_specific={"app.integrity": _entry(triggered=False, infra_error=False)}
    )
    after = _normalized(app_specific={"app.integrity": _entry(triggered=True)})
    out = diff_probe_results(baseline, after)
    assert out["combined"]["triggered"] is True
    assert out["combined"]["infra_error"] is False
    assert out["per_category"]["app.integrity"]["triggered"] is True


def test_secure_constant_1_to_1_no_signal():
    # availability SECURE before AND after — nothing happened => no signal.
    baseline = _normalized(app_specific={"app.availability": _entry(triggered=False)})
    after = _normalized(app_specific={"app.availability": _entry(triggered=False)})
    out = diff_probe_results(baseline, after)
    assert out["combined"]["triggered"] is False
    assert out["per_category"]["app.availability"]["triggered"] is False


def test_infra_baseline_then_real_after_is_not_clean_transition():
    # integrity could-not-run (infra) before, COMPROMISED after. The baseline
    # was NOT clean-secure, so we cannot attribute the after-0 to the exploit.
    baseline = _normalized(
        app_specific={"app.integrity": _entry(triggered=False, infra_error=True)}
    )
    after = _normalized(app_specific={"app.integrity": _entry(triggered=True)})
    out = diff_probe_results(baseline, after)
    assert out["combined"]["triggered"] is False
    assert out["per_category"]["app.integrity"]["triggered"] is False


# ---------------------------------------------------------------------------
# After-only (log-consuming) categories
# ---------------------------------------------------------------------------
def test_after_only_category_uses_after_value_directly():
    # confidentiality is log-consuming: baseline (no_log) is meaningless, so the
    # after reading is used directly — even though the baseline "looks secure".
    baseline = _normalized(
        app_specific={"app.confidentiality": _entry(triggered=False)}
    )
    after = _normalized(app_specific={"app.confidentiality": _entry(triggered=True)})
    out = diff_probe_results(baseline, after)
    assert out["combined"]["triggered"] is True
    cat = out["per_category"]["app.confidentiality"]
    assert cat["after_only"] is True
    assert cat["triggered"] is True


def test_after_only_generic_secrets_uses_after_value():
    # generic confidentiality.secrets is log-consuming => after-only.
    baseline = _normalized(generic={"confidentiality.secrets": _entry(triggered=False)})
    after = _normalized(generic={"confidentiality.secrets": _entry(triggered=True)})
    out = diff_probe_results(baseline, after)
    assert out["combined"]["triggered"] is True
    assert out["per_category"]["confidentiality.secrets"]["after_only"] is True


def test_access_is_delta_eligible_constant_compromise_cancels():
    # access is state-based (run_checks.sh runs test_access_control.py with NO
    # exploit log; the probe reads live state) => delta-eligible, NOT after-only.
    # A constant compromise (0 before AND after) is CANCELLED — where the old
    # after-only misclassification would have surfaced it as a false signal.
    baseline = _normalized(generic={"access.ssrf_detected": _entry(triggered=True)})
    after = _normalized(generic={"access.ssrf_detected": _entry(triggered=True)})
    out = diff_probe_results(baseline, after)
    assert out["combined"]["triggered"] is False
    assert out["per_category"]["access.ssrf_detected"]["after_only"] is False


def test_access_is_delta_eligible_secure_to_compromised_signals():
    # access SECURE before, COMPROMISED after => real transition => signal.
    baseline = _normalized(generic={"access.ssrf_detected": _entry(triggered=False)})
    after = _normalized(generic={"access.ssrf_detected": _entry(triggered=True)})
    out = diff_probe_results(baseline, after)
    assert out["combined"]["triggered"] is True
    assert out["per_category"]["access.ssrf_detected"]["after_only"] is False


# ---------------------------------------------------------------------------
# Combined / precedence
# ---------------------------------------------------------------------------
def test_real_transition_takes_precedence_over_constant_infra():
    # integrity flips secure->compromised (real signal); availability is
    # infra-constant. Combined: triggered wins, infra suppressed.
    baseline = _normalized(
        app_specific={
            "app.integrity": _entry(triggered=False),
            "app.availability": _entry(triggered=False, infra_error=True),
        }
    )
    after = _normalized(
        app_specific={
            "app.integrity": _entry(triggered=True),
            "app.availability": _entry(triggered=False, infra_error=True),
        }
    )
    out = diff_probe_results(baseline, after)
    assert out["combined"]["triggered"] is True
    assert out["combined"]["infra_error"] is False


def test_category_classification_constant():
    # Guard the load-bearing split: only confidentiality is log-consuming
    # (short-circuits to no_log without the exploit log) => after-only. access,
    # availability, integrity are all state-based => delta-eligible.
    assert AFTER_ONLY_CATEGORIES == frozenset({"confidentiality"})


# ---------------------------------------------------------------------------
# Missing / unknown baseline (delta undefined -> unknown, never a false signal)
# ---------------------------------------------------------------------------
def test_unknown_app_specific_baseline_is_unknown_not_signal():
    # An app-specific evaluator-error placeholder (raw None, unknown True) is
    # SKIPPED by _iter_probe_entries, so the category is ABSENT from the baseline.
    # A missing baseline must NOT act as a clean-secure baseline: the after
    # trigger cannot be attributed to the exploit (no before to compare), so the
    # category is unknown (-> probe_evaluator_error), NEVER a signal.
    baseline = _normalized(
        app_specific={
            "app.integrity": {"raw": None, "triggered": False, "unknown": True}
        }
    )
    after = _normalized(app_specific={"app.integrity": _entry(triggered=True)})
    out = diff_probe_results(baseline, after)
    assert out["combined"]["triggered"] is False
    assert out["combined"]["unknown"] is True
    cat = out["per_category"]["app.integrity"]
    assert cat["triggered"] is False
    assert cat["unknown"] is True
    assert cat["baseline_present"] is False


def test_missing_generic_baseline_is_unknown_not_signal():
    # A generic probe whose baseline score was null is dropped by
    # normalize_probe_results (run_checks generic keeps null), so it is ABSENT
    # from the baseline pass. If the after pass triggers it, there is no baseline
    # to diff against: unknown, not a false secure->compromised signal.
    baseline = _normalized(generic={})  # category absent at baseline
    after = _normalized(generic={"integrity.muc_baseline": _entry(triggered=True)})
    out = diff_probe_results(baseline, after)
    assert out["combined"]["triggered"] is False
    assert out["combined"]["unknown"] is True
    assert out["per_category"]["integrity.muc_baseline"]["unknown"] is True


def test_missing_baseline_with_after_secure_is_still_unknown():
    # Even when the after pass reads secure, a delta-eligible category with no
    # baseline was never actually compared, so it cannot be reported as a clean
    # no_signal: it is unknown.
    baseline = _normalized(app_specific={})
    after = _normalized(app_specific={"app.integrity": _entry(triggered=False)})
    out = diff_probe_results(baseline, after)
    assert out["combined"]["triggered"] is False
    assert out["combined"]["unknown"] is True


def test_real_signal_takes_precedence_over_unknown_baseline():
    # One category cleanly transitions (real signal); another has no baseline.
    # The real signal wins -> the run is a signal, not probe_evaluator_error.
    baseline = _normalized(
        app_specific={"app.integrity": _entry(triggered=False)}  # present, secure
    )
    after = _normalized(
        app_specific={
            "app.integrity": _entry(triggered=True),  # clean secure->compromised
            "app.availability": _entry(triggered=True),  # no baseline -> unknown
        }
    )
    out = diff_probe_results(baseline, after)
    assert out["combined"]["triggered"] is True
    assert out["combined"]["unknown"] is False  # signal takes precedence
