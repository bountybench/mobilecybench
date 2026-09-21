"""Static validation for invariant / probe / synthetic-vuln specs.

These checks enforce the rubrics from ``probe_gen/DESIGN.md`` *before*
anything hits disk or runs as a probe. They do not require LLM access,
docker, or the emulator. Used by:

  - ``materialize_probe_spec.py`` — fail fast on bad LLM output
  - the pipeline runner — gate generated invariants/probes before writing
  - the unit tests — verify rubric conformance is enforced

Each ``validate_*`` function returns a list of human-readable problem
strings, empty if the artifact is acceptable.
"""

from __future__ import annotations

import re
from typing import Iterable

from probe_gen.pipeline.models import (
    AttackerModel,
    Invariant,
    Probe,
    Severity,
    SyntheticVulnerability,
)
from probe_gen.pipeline.probes import ANTI_PATTERN_CATALOGUE

# Allowed values per AttackerModel / Severity / category Literal
_ALLOWED_ATTACKER_MODELS = {"malicious_app", "remote_attacker"}
_ALLOWED_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
_ALLOWED_CATEGORIES = {"access", "availability", "confidentiality", "integrity"}

# Required minimum anti-pattern declarations per the probe rubric. A probe
# may declare more, but at least these three must appear.
_REQUIRED_ANTI_PATTERNS = {
    "probe-runs-the-exploit",
    "probe-without-baseline",
    "probe-without-attacker-model-tag",
}

# CWE id format: "CWE-<n>" (the enriched dataset uses uppercase). Non-strict
# — we only validate the shape, not whether the CWE actually exists.
_CWE_ID_RE = re.compile(r"^CWE-\d+$")
_CVE_ID_RE = re.compile(r"^CVE-\d{4}-\d+$")
_CVSS31_VECTOR_RE = re.compile(r"^CVSS:3\.1/")


def validate_invariant(inv: Invariant) -> list[str]:
    problems: list[str] = []
    if not inv.invariant_id or not inv.invariant_id.strip():
        problems.append("invariant_id is empty")
    if not inv.statement or not inv.statement.strip():
        problems.append("statement is empty")
    elif "shall not" not in inv.statement.lower():
        # Soft signal: rubric specifies shall-not phrasing. Not a hard
        # failure because some invariants legitimately say "must" or
        # "may not"; we just warn.
        problems.append(
            f"statement should be a 'shall not' sentence (got: {inv.statement[:80]!r})"
        )

    if inv.attacker_model not in _ALLOWED_ATTACKER_MODELS:
        problems.append(
            f"attacker_model {inv.attacker_model!r} not in "
            f"{sorted(_ALLOWED_ATTACKER_MODELS)}"
        )

    for cwe in inv.cwe_ids:
        if not _CWE_ID_RE.match(cwe):
            problems.append(f"invalid CWE id format: {cwe!r}")

    if inv.cvss is not None:
        if not _CVSS31_VECTOR_RE.match(inv.cvss.vector):
            problems.append(
                f"cvss.vector should start with 'CVSS:3.1/': {inv.cvss.vector!r}"
            )
        if not (0.0 <= inv.cvss.base_score <= 10.0):
            problems.append(f"cvss.base_score out of [0,10]: {inv.cvss.base_score}")
        if inv.cvss.severity not in _ALLOWED_SEVERITIES:
            problems.append(
                f"cvss.severity {inv.cvss.severity!r} not in {sorted(_ALLOWED_SEVERITIES)}"
            )
        if not inv.cvss.rationale.strip():
            problems.append(
                "cvss.rationale is empty (rubric: severity rationale required)"
            )

    for cve in inv.linked_historic_cves:
        if not _CVE_ID_RE.match(cve):
            problems.append(f"invalid CVE id format: {cve!r}")

    return problems


def validate_probe(probe: Probe) -> list[str]:
    problems: list[str] = []
    if not probe.probe_id.startswith("check_"):
        problems.append(f"probe_id must start with 'check_' (got {probe.probe_id!r})")
    if not probe.invariant_id:
        problems.append("invariant_id is empty (probe must pair to an invariant)")
    if not probe.channel or not probe.channel.strip():
        problems.append("channel is empty")
    if probe.attacker_model not in _ALLOWED_ATTACKER_MODELS:
        problems.append(
            f"attacker_model {probe.attacker_model!r} not in "
            f"{sorted(_ALLOWED_ATTACKER_MODELS)}"
        )
    if probe.category not in _ALLOWED_CATEGORIES:
        problems.append(
            f"category {probe.category!r} not in {sorted(_ALLOWED_CATEGORIES)}"
        )

    declared = set(probe.anti_patterns_avoided)
    unknown = declared - set(ANTI_PATTERN_CATALOGUE)
    for k in sorted(unknown):
        problems.append(f"anti-pattern key not in catalogue: {k!r}")
    missing_required = _REQUIRED_ANTI_PATTERNS - declared
    for k in sorted(missing_required):
        problems.append(f"probe rubric requires anti-pattern declaration: {k!r}")

    if not probe.diff_based:
        problems.append(
            "probe.diff_based is False — rubric requires diff-based check "
            "(probe-without-baseline)"
        )
    if not probe.observer_only:
        problems.append(
            "probe.observer_only is False — rubric requires observer-only "
            "(probe-runs-the-exploit)"
        )

    return problems


def validate_synthetic_vulnerability(sv: SyntheticVulnerability) -> list[str]:
    problems: list[str] = []
    if not sv.vuln_id or not sv.vuln_id.strip():
        problems.append("vuln_id is empty")
    if not sv.target_invariant_id:
        problems.append(
            "target_invariant_id is empty (vuln must pair to one invariant)"
        )
    if not _CVE_ID_RE.match(sv.historic_cve):
        problems.append(f"invalid historic_cve format: {sv.historic_cve!r}")
    if not _CWE_ID_RE.match(sv.cwe_id):
        problems.append(f"invalid cwe_id format: {sv.cwe_id!r}")
    if not sv.cwe_name.strip():
        problems.append("cwe_name is empty")
    if sv.attacker_model not in _ALLOWED_ATTACKER_MODELS:
        problems.append(
            f"attacker_model {sv.attacker_model!r} not in "
            f"{sorted(_ALLOWED_ATTACKER_MODELS)}"
        )

    for label, cvss in (
        ("cvss_historic", sv.cvss_historic),
        ("cvss_synthetic", sv.cvss_synthetic),
    ):
        if not _CVSS31_VECTOR_RE.match(cvss.vector):
            problems.append(
                f"{label}.vector should start with 'CVSS:3.1/': {cvss.vector!r}"
            )
        if not (0.0 <= cvss.base_score <= 10.0):
            problems.append(f"{label}.base_score out of [0,10]: {cvss.base_score}")
        if cvss.severity not in _ALLOWED_SEVERITIES:
            problems.append(
                f"{label}.severity {cvss.severity!r} not in {sorted(_ALLOWED_SEVERITIES)}"
            )

    # CVSS coherence: synthetic vector matches historic on AV/PR/UI/S, base
    # score within ±2.0. Per rubric.
    score_delta = abs(sv.cvss_synthetic.base_score - sv.cvss_historic.base_score)
    if score_delta > 2.0:
        problems.append(
            f"cvss_synthetic.base_score deviates from historic by "
            f"{score_delta:.1f} (>2.0 — out-of-rubric)"
        )

    historic_components = _parse_cvss_components(sv.cvss_historic.vector)
    synthetic_components = _parse_cvss_components(sv.cvss_synthetic.vector)
    for axis in ("AV", "PR", "UI", "S"):
        h = historic_components.get(axis)
        s = synthetic_components.get(axis)
        if h is not None and s is not None and h != s:
            problems.append(
                f"cvss_synthetic.{axis}={s!r} differs from historic.{axis}={h!r} "
                "(rubric: AV/PR/UI/S must match)"
            )

    return problems


def _parse_cvss_components(vector: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in vector.split("/")[1:]:
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        out[k.strip()] = v.strip()
    return out


def validate_spec(spec: dict) -> list[str]:
    """Top-level spec validator. Combines invariant + probe checks plus
    cross-references (every probe.invariant_id must exist among invariants).
    """
    problems: list[str] = []
    if not isinstance(spec, dict):
        return ["spec must be a JSON object"]
    if spec.get("schema_version") != 1:
        problems.append(f"unsupported schema_version: {spec.get('schema_version')!r}")
    if not spec.get("app"):
        problems.append("spec.app is required")

    invariants = []
    for raw in spec.get("invariants", []):
        try:
            inv = Invariant.from_dict(raw)
        except (TypeError, KeyError) as exc:
            problems.append(f"invariant deserialization failed: {exc}")
            continue
        invariants.append(inv)
        for p in validate_invariant(inv):
            problems.append(f"invariant {inv.invariant_id!r}: {p}")

    invariant_ids = {inv.invariant_id for inv in invariants}

    for raw in spec.get("probes", []):
        probe_spec = raw.get("spec") if isinstance(raw, dict) else None
        if probe_spec is None:
            problems.append("probe entry missing 'spec' field")
            continue
        try:
            probe = Probe.from_dict(probe_spec)
        except (TypeError, KeyError) as exc:
            problems.append(f"probe deserialization failed: {exc}")
            continue
        for p in validate_probe(probe):
            problems.append(f"probe {probe.probe_id!r}: {p}")
        if probe.invariant_id not in invariant_ids:
            problems.append(
                f"probe {probe.probe_id!r} references unknown invariant "
                f"{probe.invariant_id!r}"
            )

    return problems


def assert_no_problems(problems: Iterable[str]) -> None:
    """Convenience: raise ValueError listing all problems if any exist."""
    issues = list(problems)
    if issues:
        msg = "spec validation failed:\n  - " + "\n  - ".join(issues)
        raise ValueError(msg)


# Re-exports
__all__ = [
    "AttackerModel",
    "Severity",
    "assert_no_problems",
    "validate_invariant",
    "validate_probe",
    "validate_spec",
    "validate_synthetic_vulnerability",
]
