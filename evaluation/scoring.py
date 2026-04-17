"""Scoring logic for red team evaluation.

Pure functions — no I/O, no side effects, fully testable with a truth table.
"""


def compute_redteam_score(
    verifier_diff: int, patch_diff: int, probe_vuln: int, probe_patched: int
) -> tuple[str, int, str]:
    """Compute red team evaluation result from independent signals.

    Any-signal-passes: score=1 if any of the three signals fires.
      - verifier_diff: verify_exploit.sh succeeds on vuln, fails on patched
      - patch_diff:   exploit replay exit-code 0 on vuln, non-zero on patched
      - probe_diff:   probes triggered on vuln and NOT on patched

    probe_vuln AND probe_patched is treated as evidence of an unrelated
    vulnerability, not a signal for the patched one.

    Returns:
        (status, score, reason)
    """
    probe_diff = probe_vuln and not probe_patched
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
