"""CVE → invariant coverage matrix generation.

Phase 1.5 of the pipeline: for each in-tree app, audit which historic CVEs
are caught by which invariants. Apps inherit which CVEs to consider via
their archetype's CWE focus and via direct CVE pairings declared on
invariants (``Invariant.linked_historic_cves``).

This module is pure-Python, no I/O beyond reading the existing
``experimental/android_*_enriched.jsonl`` dataset.

Output shape (consumed by ``probe_coverage_matrix.md`` renderer):

    {
        "app": "conversations",
        "rows": [
            {
                "cve_id": "CVE-2025-27916",
                "cwe_ids": ["CWE-290"],
                "severity": "HIGH",
                "covering_invariants": ["RA-X1"],
                "covering_probes": ["check_..."],
                "gap": False,
            },
            ...
        ],
        "summary": {"total": 50, "covered": 47, "gap": 3},
    }
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from probe_gen.pipeline.models import Invariant, Probe


@dataclass
class CVERecord:
    cve_id: str
    cwe_ids: list[str]  # Union of nvd/vendor/adp CWEs
    severity: Optional[str]  # HIGH/MEDIUM/LOW/CRITICAL
    base_score: Optional[float]
    attack_vector: Optional[str]
    privileges_required: Optional[str]
    user_interaction: Optional[str]
    confidence: Optional[float]
    description: str = ""

    @classmethod
    def from_enriched(cls, d: dict) -> "CVERecord":
        cwes = (
            list(d.get("nvd_cwe_ids") or [])
            + list(d.get("vendor_cwe_ids") or [])
            + list(d.get("adp_cwe_ids") or [])
        )
        # Dedup preserving order
        seen: set[str] = set()
        cwe_ids = []
        for c in cwes:
            if c not in seen:
                cwe_ids.append(c)
                seen.add(c)
        return cls(
            cve_id=d.get("cve_id", ""),
            cwe_ids=cwe_ids,
            severity=d.get("nvd_cvss31_severity")
            or d.get("vendor_cvss31_severity")
            or d.get("adp_cvss31_severity"),
            base_score=d.get("nvd_cvss31_base_score")
            or d.get("vendor_cvss31_base_score")
            or d.get("adp_cvss31_base_score"),
            attack_vector=d.get("nvd_cvss31_attack_vector")
            or d.get("vendor_cvss31_attack_vector")
            or d.get("adp_cvss31_attack_vector"),
            privileges_required=d.get("nvd_cvss31_privileges_required")
            or d.get("vendor_cvss31_privileges_required")
            or d.get("adp_cvss31_privileges_required"),
            user_interaction=d.get("nvd_cvss31_user_interaction")
            or d.get("vendor_cvss31_user_interaction")
            or d.get("adp_cvss31_user_interaction"),
            confidence=d.get("confidence"),
            description=d.get("reason", "") or d.get("original_reason", ""),
        )


def load_enriched_dataset(paths: Iterable[Path]) -> list[CVERecord]:
    """Load CVE records from one or more enriched .jsonl files."""
    out: list[CVERecord] = []
    for path in paths:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                # Only include entries that the enrichment classified as Android-affecting
                if d.get("android") is False:
                    continue
                out.append(CVERecord.from_enriched(d))
    return out


def filter_by_archetype_cwes(
    records: Iterable[CVERecord],
    archetype_cwe_focus: Iterable[str],
) -> list[CVERecord]:
    focus = set(archetype_cwe_focus)
    return [r for r in records if any(c in focus for c in r.cwe_ids)]


@dataclass
class CoverageRow:
    cve: CVERecord
    covering_invariants: list[str]  # invariant_ids
    covering_probes: list[str]  # probe_ids
    gap: bool

    def to_dict(self) -> dict:
        return {
            "cve_id": self.cve.cve_id,
            "cwe_ids": self.cve.cwe_ids,
            "severity": self.cve.severity,
            "base_score": self.cve.base_score,
            "covering_invariants": self.covering_invariants,
            "covering_probes": self.covering_probes,
            "gap": self.gap,
        }


def build_coverage_matrix(
    cves: Iterable[CVERecord],
    invariants: Iterable[Invariant],
    probes: Iterable[Probe],
) -> list[CoverageRow]:
    """For each CVE, find which invariants and probes cover it.

    Two coverage signals:
      1. Direct: invariant.linked_historic_cves contains the CVE id
      2. CWE class match: invariant.cwe_ids ∩ cve.cwe_ids non-empty

    A CVE is considered "covered" if either signal is true for ≥1 invariant.
    """
    invariants = list(invariants)
    probes_by_invariant: dict[str, list[Probe]] = {}
    for p in probes:
        probes_by_invariant.setdefault(p.invariant_id, []).append(p)

    rows: list[CoverageRow] = []
    for cve in cves:
        cve_cwe_set = set(cve.cwe_ids)
        covering_inv: list[str] = []
        for inv in invariants:
            if cve.cve_id in inv.linked_historic_cves:
                covering_inv.append(inv.invariant_id)
                continue
            if cve_cwe_set & set(inv.cwe_ids):
                covering_inv.append(inv.invariant_id)
        covering_probe_ids: list[str] = []
        for inv_id in covering_inv:
            for p in probes_by_invariant.get(inv_id, []):
                covering_probe_ids.append(p.probe_id)
        rows.append(
            CoverageRow(
                cve=cve,
                covering_invariants=covering_inv,
                covering_probes=covering_probe_ids,
                gap=not covering_inv,
            )
        )
    return rows


def render_coverage_matrix_md(app: str, rows: list[CoverageRow]) -> str:
    total = len(rows)
    covered = sum(1 for r in rows if not r.gap)
    gaps = total - covered

    lines: list[str] = []
    lines.append(f"# CVE coverage matrix — {app}")
    lines.append("")
    lines.append(
        f"- Total in-scope CVEs: **{total}**  "
        f"|  Covered: **{covered}**  |  Gaps: **{gaps}** "
        f"({(100.0 * covered / total) if total else 0.0:.1f}% coverage)"
    )
    lines.append("")
    lines.append(
        "Coverage signal: invariant directly cites the CVE (`linked_historic_cves`) "
        "OR shares ≥1 CWE class with it. Gaps are CVEs no invariant in the suite catches yet."
    )
    lines.append("")
    lines.append("| CVE | CWEs | Severity | Score | Invariants | Probes | Status |")
    lines.append("|---|---|---|---:|---|---|---|")
    # Sort: gaps first (force coverage attention), then by base score desc
    sorted_rows = sorted(
        rows,
        key=lambda r: (
            not r.gap,
            -(r.cve.base_score or 0.0),
            r.cve.cve_id,
        ),
    )
    for r in sorted_rows:
        cwes = ", ".join(r.cve.cwe_ids) or "—"
        sev = r.cve.severity or "—"
        score = f"{r.cve.base_score:.1f}" if r.cve.base_score is not None else "—"
        invs = ", ".join(r.covering_invariants) or "—"
        probes = ", ".join(r.covering_probes) or "—"
        status = "**GAP**" if r.gap else "covered"
        lines.append(
            f"| {r.cve.cve_id} | {cwes} | {sev} | {score} | {invs} | {probes} | {status} |"
        )
    lines.append("")
    if gaps:
        lines.append("## Gaps requiring new invariants")
        lines.append("")
        for r in sorted_rows:
            if not r.gap:
                continue
            lines.append(
                f"- {r.cve.cve_id} (CWE: {', '.join(r.cve.cwe_ids) or 'unknown'}, "
                f"severity: {r.cve.severity or 'unknown'})"
            )
        lines.append("")
    return "\n".join(lines)
