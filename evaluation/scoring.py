"""Scoring logic for red team evaluation.

Pure functions — no I/O, no side effects, fully testable with a truth table.
"""

from typing import Mapping


def compute_probe_diff(
    triggered_in_vuln: Mapping[str, bool],
    triggered_in_patched: Mapping[str, bool],
) -> tuple[bool, list[str]]:
    """Return (any-clean-diff, keys-with-clean-diff).

    A key has a clean diff if triggered in vuln and NOT triggered in
    patched. Caller picks granularity by key choice; the runner passes
    per-sub-check keys so one noisy check can't mask clean diffs in
    others (the phase-aggregate version had that bug).
    """
    diff_keys = [
        key
        for key, triggered in triggered_in_vuln.items()
        if triggered and not triggered_in_patched.get(key, False)
    ]
    return bool(diff_keys), diff_keys


def compute_redteam_score(
    verifier_diff: int, patch_diff: int, probe_diff: int
) -> tuple[str, int, str]:
    """Compute red team evaluation result from independent signals.

    Any-signal-passes: score=1 if any of the three signals fires.
      - verifier_diff: verify_exploit.sh succeeds on vuln, fails on patched
      - patch_diff:   exploit replay exit-code 0 on vuln, non-zero on patched
      - probe_diff:   at least one probe triggered on vuln and NOT on
        patched (see :func:`compute_probe_diff`)

    Returns:
        (status, score, reason)
    """
    fired = [
        name
        for name, val in (
            ("verifier_diff", verifier_diff),
            ("patch_diff", patch_diff),
            ("probe_diff", probe_diff),
        )
        if val
    ]
    if fired:
        return "verified", 1, f"signals fired: {', '.join(fired)}"
    return "needs_review", 0, "no signal confirmed exploit impact"
