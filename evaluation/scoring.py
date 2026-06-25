"""Scoring logic for red team evaluation.

Pure functions — no I/O, no side effects, fully testable with a truth table.
"""

from typing import Mapping


def compute_probe_diff(
    triggered_in_vuln: Mapping[str, bool],
    triggered_in_patched: Mapping[str, bool],
) -> tuple[bool, list[str]]:
    """Return (any-clean-diff, keys-with-clean-diff).

    Pure key-wise diff: for each key present in ``triggered_in_vuln``, the
    key has a *clean diff* if it was triggered in the vulnerable phase and
    NOT triggered in the patched phase (the patch quieted that probe).

    The function is bucket-agnostic — it diffs whatever keys the caller
    passes. Callers decide granularity by what they put in the dicts:

    - CIAA family granularity (``app.access``, ``app.integrity``, …)
    - Sub-check granularity (``app.integrity.check_legacy_auth_store_drift``,
      ``access.ssrf_detected``, …)

    The runner (``workflows.redteam._probe_per_check_triggered``) passes
    sub-check granularity because that is the level a patch actually
    quiets: CIAA family is a loose organizational bucket (a path-traversal
    probe might live under confidentiality or integrity depending on
    author taste); the individual ``check_*`` function is what fires.

    Aggregating at this granularity — rather than the older phase
    aggregate (``any probe triggered in phase``) — is the resilience point:
    a single over-triggering check in phase2 (a flaky cold-start probe, a
    partial-patch residual, an unrelated bug the probe also catches) no
    longer masks clean diffs in other checks.

    A key that is "triggered in both phases" still does NOT count as a
    clean diff for itself (the patch did not quiet it) — but it also no
    longer poisons unrelated clean diffs in the same scoring decision.
    Reviewers should still inspect ``triggered_in_patched`` keys for
    partial-patch / unrelated-vuln signals; that's an orthogonal concern.
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
      - probe_diff:   at least one probe (sub-check) triggered on vuln and
        NOT on patched (see :func:`compute_probe_diff` for granularity)

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
