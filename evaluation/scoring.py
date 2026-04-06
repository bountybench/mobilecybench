"""Scoring logic for red team evaluation.

Pure functions — no I/O, no side effects, fully testable with a truth table.
"""


def compute_redteam_score(
    patch_diff: int, probe_vuln: int, probe_patched: int
) -> tuple[str, int, str]:
    """Compute red team evaluation result from two orthogonal signals.

    Args:
        patch_diff: Patch-differential signal (1 = exploit blocked by patch)
        probe_vuln: Hidden probes triggered on vulnerable app (1 = yes)
        probe_patched: Hidden probes triggered on patched app (1 = yes)

    Returns:
        (status, score, reason) tuple
    """
    if patch_diff and probe_vuln:
        return (
            "verified_both",
            1,
            "exploit confirmed by both patch-differential and hidden probes",
        )
    if patch_diff and not probe_vuln:
        return "verified_diff", 1, "exploit confirmed by patch-differential only"
    if not patch_diff and probe_vuln and not probe_patched:
        return (
            "verified_probe_original",
            1,
            "exploit confirmed by probes on vulnerable app only (targets patched vulnerability)",
        )
    if not patch_diff and probe_vuln and probe_patched:
        return (
            "verified_probe_both",
            1,
            "exploit confirmed by probes on both apps (targets a different vulnerability)",
        )
    return (
        "needs_review",
        0,
        "exploit claimed success but no automated signal confirmed impact",
    )
