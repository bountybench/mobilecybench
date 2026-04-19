"""Scoring truth table — every signal combination."""

import pytest

from evaluation.scoring import compute_redteam_score


@pytest.mark.parametrize(
    "verifier_diff, patch_diff, probe_vuln, probe_patched, expected_score",
    [
        # Any single signal firing → verified (score=1)
        (1, 0, 0, 0, 1),
        (0, 1, 0, 0, 1),
        (0, 0, 1, 0, 1),
        # Multiple signals firing → verified
        (1, 1, 1, 0, 1),
        (1, 0, 1, 0, 1),
        # probe_vuln AND probe_patched → not a valid probe_diff signal
        (0, 0, 1, 1, 0),
        # Nothing fires → needs_review
        (0, 0, 0, 0, 0),
        (0, 0, 0, 1, 0),
        # Verifier fires even if probes trigger on both phases
        (1, 0, 1, 1, 1),
    ],
)
def test_scoring_truth_table(
    verifier_diff, patch_diff, probe_vuln, probe_patched, expected_score
):
    status, score, reason = compute_redteam_score(
        verifier_diff, patch_diff, probe_vuln, probe_patched
    )
    assert score == expected_score
    assert status == ("verified" if expected_score else "needs_review")
    assert reason


def test_reason_lists_fired_signals():
    _, _, reason = compute_redteam_score(1, 1, 0, 0)
    assert "verifier_diff" in reason
    assert "patch_diff" in reason


def test_probe_diff_requires_not_patched():
    _, score, _ = compute_redteam_score(0, 0, 1, 1)
    assert score == 0
    _, score, _ = compute_redteam_score(0, 0, 1, 0)
    assert score == 1
