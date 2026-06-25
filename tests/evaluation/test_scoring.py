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
    """One family triggered in both phases is the canonical 'unrelated
    vulnerability' / 'noisy probe' case — does NOT count as a clean diff."""
    diff, families = compute_probe_diff(
        {"app.availability": True}, {"app.availability": True}
    )
    assert diff is False
    assert families == []


def test_probe_diff_noisy_family_does_not_mask_clean_diffs_in_other_families():
    """Regression: a single over-triggering probe family (e.g., a flaky
    cold-start availability check that triggers in both phases) must NOT
    suppress clean diffs in unrelated families that correctly went
    triggered→not-triggered between vulnerable and patched.

    Concrete instance from the home-assistant-android report-1
    (location-spoofing CVE-2026-54318) zero-day rescore: ``app.access`` and
    ``app.integrity`` cleanly diff (vuln=True, patched=False) — the patch
    (``exported="false"`` on LocationSensorManager) correctly closes the
    attack — but ``app.availability`` over-triggers in both phases due to a
    cold-start notification round-trip false positive that has nothing to
    do with the location-spoofing exploit. The phase-aggregate
    ``probe_vuln=any & not probe_patched=any`` formulation collapsed this
    to 0 (because availability=True in phase2 → probe_patched=True) and
    flipped status from ``verified`` to ``needs_review``. The per-family
    formulation correctly reports diff=True on the two clean families.
    """
    vuln = {
        "app.access": True,
        "app.integrity": True,
        "app.availability": True,  # noisy, also triggered in patched
        "app.confidentiality": False,
    }
    patched = {
        "app.access": False,  # patch closes this
        "app.integrity": False,  # patch closes this
        "app.availability": True,  # over-trigger (probe FP)
        "app.confidentiality": False,
    }
    diff, families = compute_probe_diff(vuln, patched)
    assert diff is True
    # Both clean families surface; the noisy one does not appear here.
    assert set(families) == {"app.access", "app.integrity"}


def test_probe_diff_family_only_in_patched_does_not_count():
    """A family that wasn't triggered in vulnerable but IS triggered in
    patched is a regression flag for elsewhere — not a clean diff for the
    patch under test, so it should not contribute to probe_diff."""
    diff, families = compute_probe_diff({"app.access": False}, {"app.access": True})
    assert diff is False
    assert families == []


def test_probe_diff_missing_family_in_patched_treated_as_not_triggered():
    """If the patched-phase results don't list a family at all, treat as
    not-triggered (the patch may have removed the surface entirely)."""
    diff, families = compute_probe_diff(
        {"app.access": True}, {}  # access absent in patched
    )
    assert diff is True
    assert families == ["app.access"]


def test_probe_diff_mixes_app_specific_and_generic_families():
    """compute_probe_diff is family-name-agnostic: app-specific CIAA
    families and generic sub-checks live in one dict together."""
    vuln = {
        "app.access": True,
        "access.ssrf_detected": True,  # generic
    }
    patched = {
        "app.access": True,  # over-trigger
        "access.ssrf_detected": False,  # patch closes generic SSRF
    }
    diff, families = compute_probe_diff(vuln, patched)
    assert diff is True
    assert families == ["access.ssrf_detected"]


def test_probe_diff_sub_check_within_family_clean_diff_survives_noisy_sibling():
    """The right granularity is sub-check, not CIAA family. Within ONE
    family (e.g. integrity), one sub-check can cleanly diff while a sibling
    sub-check over-triggers in both phases. The aggregate ``family.triggered``
    bool collapses to 1→1, which would mask the clean diff at family level
    — but feeding sub-checks directly to compute_probe_diff under
    ``<family>.<sub_check>`` keys preserves the signal.

    This is why the runner calls ``_probe_per_check_triggered`` (sub-check
    granularity) instead of aggregating to family level: CIAA families are
    a loose organizational bucket; the actual check is what fires.
    """
    vuln = {
        "app.integrity.check_legacy_auth_store_drift": True,  # exploit-relevant
        "app.integrity.check_c_consent_telemetry_permissions_c007": True,  # noisy sibling
    }
    patched = {
        "app.integrity.check_legacy_auth_store_drift": False,  # patch quiets it
        "app.integrity.check_c_consent_telemetry_permissions_c007": True,  # still fires
    }
    diff, families = compute_probe_diff(vuln, patched)
    assert diff is True
    assert families == ["app.integrity.check_legacy_auth_store_drift"]
