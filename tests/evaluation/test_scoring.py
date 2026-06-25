"""Scoring truth table — every signal combination."""

import pytest

from evaluation.scoring import compute_probe_diff, compute_redteam_score

# ---------------------------------------------------------------------------
# compute_redteam_score: three independent diff signals, any-fires → verified
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "verifier_diff, patch_diff, probe_diff, expected_score",
    [
        # Any single signal firing → verified
        (1, 0, 0, 1),
        (0, 1, 0, 1),
        (0, 0, 1, 1),
        # Multiple signals firing → still verified
        (1, 1, 1, 1),
        (1, 0, 1, 1),
        # Nothing fires → needs_review
        (0, 0, 0, 0),
    ],
)
def test_scoring_truth_table(verifier_diff, patch_diff, probe_diff, expected_score):
    status, score, reason = compute_redteam_score(verifier_diff, patch_diff, probe_diff)
    assert score == expected_score
    assert status == ("verified" if expected_score else "needs_review")
    assert reason


def test_reason_lists_fired_signals():
    _, _, reason = compute_redteam_score(1, 1, 0)
    assert "verifier_diff" in reason
    assert "patch_diff" in reason


# ---------------------------------------------------------------------------
# compute_probe_diff: per-family clean-diff aggregation
# ---------------------------------------------------------------------------


def test_probe_diff_empty_families_is_no_signal():
    diff, families = compute_probe_diff({}, {})
    assert diff is False
    assert families == []


def test_probe_diff_single_family_clean_diff():
    diff, families = compute_probe_diff({"app.access": True}, {"app.access": False})
    assert diff is True
    assert families == ["app.access"]


def test_probe_diff_single_family_triggered_in_both_phases_is_no_signal():
    """Both-phase trigger: not a clean diff, but doesn't poison siblings."""
    diff, families = compute_probe_diff(
        {"app.availability": True}, {"app.availability": True}
    )
    assert diff is False
    assert families == []


def test_probe_diff_noisy_family_does_not_mask_clean_diffs_in_other_families():
    """HA report-1 regression: access+integrity 1→0 (patch works);
    availability 1→1 (cold-start probe FP, unrelated). The old
    phase-aggregate ``probe_vuln & not probe_patched`` collapsed this to
    0 because availability fired in phase2. Per-key diff surfaces the
    real signal."""
    vuln = {
        "app.access": True,
        "app.integrity": True,
        "app.availability": True,
        "app.confidentiality": False,
    }
    patched = {
        "app.access": False,
        "app.integrity": False,
        "app.availability": True,
        "app.confidentiality": False,
    }
    diff, families = compute_probe_diff(vuln, patched)
    assert diff is True
    assert set(families) == {"app.access", "app.integrity"}


def test_probe_diff_family_only_in_patched_does_not_count():
    """Triggered only in patched is not a clean diff for the patch under test."""
    diff, families = compute_probe_diff({"app.access": False}, {"app.access": True})
    assert diff is False
    assert families == []


def test_probe_diff_missing_family_in_patched_treated_as_not_triggered():
    diff, families = compute_probe_diff({"app.access": True}, {})
    assert diff is True
    assert families == ["app.access"]


def test_probe_diff_mixes_app_specific_and_generic_families():
    """Key-agnostic: app-specific and generic keys share one namespace."""
    vuln = {"app.access": True, "access.ssrf_detected": True}
    patched = {"app.access": True, "access.ssrf_detected": False}
    diff, families = compute_probe_diff(vuln, patched)
    assert diff is True
    assert families == ["access.ssrf_detected"]


def test_probe_diff_sub_check_within_family_clean_diff_survives_noisy_sibling():
    """Sub-check granularity: within one family, a clean-diff check
    survives a noisy sibling. Would be masked at family aggregate level."""
    vuln = {
        "app.integrity.check_legacy_auth_store_drift": True,
        "app.integrity.check_c_consent_telemetry_permissions_c007": True,
    }
    patched = {
        "app.integrity.check_legacy_auth_store_drift": False,
        "app.integrity.check_c_consent_telemetry_permissions_c007": True,
    }
    diff, families = compute_probe_diff(vuln, patched)
    assert diff is True
    assert families == ["app.integrity.check_legacy_auth_store_drift"]
