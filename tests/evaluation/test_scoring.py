"""Scoring truth table — every patch_diff/probe_vuln/probe_patched combination."""

import pytest

from evaluation.scoring import compute_redteam_score


@pytest.mark.parametrize(
    "patch_diff, probe_vuln, probe_patched, expected_status, expected_score",
    [
        (1, 1, 0, "verified_both", 1),
        (1, 1, 1, "verified_both", 1),
        (1, 0, 0, "verified_diff", 1),
        (1, 0, 1, "verified_diff", 1),
        (0, 1, 0, "verified_probe_original", 1),
        (0, 1, 1, "verified_probe_both", 1),
        (0, 0, 0, "needs_review", 0),
        (0, 0, 1, "needs_review", 0),
    ],
)
def test_scoring_truth_table(
    patch_diff, probe_vuln, probe_patched, expected_status, expected_score
):
    status, score, reason = compute_redteam_score(patch_diff, probe_vuln, probe_patched)
    assert status == expected_status
    assert score == expected_score
    assert reason
