#!/usr/bin/env python3
"""End-to-end status report for one app.

Combines:
  - Modernization audit (which canonical artifacts exist)
  - Archetype assignment + invariant template count
  - CVE coverage matrix preview (no invariants supplied → all CVEs as gaps)
  - Existing synthetic-vulnerability inventory

Output: a single Markdown document under
``probe_gen/runs/app_status_<app>_<ts>/`` that gives a reviewer the
"current state" view for one app at a glance.

Pure-Python, no LLM or docker dependency.

Usage::

    python probe_gen/scripts/app_status.py --app conversations
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from probe_gen.pipeline.archetypes import (  # noqa: E402
    get_archetype,
    list_known_apps,
)
from probe_gen.pipeline.coverage import (  # noqa: E402
    build_coverage_matrix,
    filter_by_archetype_cwes,
    load_enriched_dataset,
)

# Reuse the audit-script artifact taxonomy for consistency.
ARTIFACTS = [
    ("threat_model.md", "threat_model.md", "file"),
    ("checks/", "checks", "dir"),
    ("probe_lib.py", "probe_lib.py", "file"),
    ("probe_common.py", "probe_common.py", "file"),
    ("seed_baseline.py", "seed_baseline.py", "file"),
    ("remote_attacker/", "remote_attacker", "dir"),
    ("probe_config_rationale.md", "probe_config_rationale.md", "file"),
    ("probe_test_plan.md", "probe_test_plan.md", "file"),
]


def _check_artifact(app_dir: Path, rel: str, kind: str) -> bool:
    p = app_dir / rel
    if kind == "file":
        return p.is_file()
    if kind == "dir":
        return p.is_dir() and any(p.iterdir())
    return False


def _list_synth_vulns(app_dir: Path) -> list[str]:
    vd = app_dir / "synthetic_vulnerabilities"
    if not vd.is_dir():
        return []
    return sorted(c.name for c in vd.iterdir() if c.is_dir())


def _list_existing_probes(app_dir: Path) -> dict[str, list[str]]:
    """Return {scope: [check_*.py, ...]} for malicious_app and remote_attacker."""
    out: dict[str, list[str]] = {"malicious_app": [], "remote_attacker": []}
    for d, label in (
        (app_dir / "checks", "malicious_app"),
        (app_dir / "remote_attacker" / "checks", "remote_attacker"),
    ):
        if d.is_dir():
            out[label] = sorted(
                c.stem
                for c in d.iterdir()
                if c.is_file() and c.name.startswith("check_")
            )
    return out


def render_status_md(app: str, app_dir: Path, repo_root: Path) -> str:
    lines: list[str] = []
    lines.append(f"# App status: {app}")
    lines.append("")
    profile = get_archetype(app)
    lines.append(f"- Archetype: **{profile.name}**")
    lines.append(f"- Default CWE focus: {', '.join(profile.cwe_focus)}")
    lines.append(
        f"- Archetype invariant templates available: {len(profile.invariant_templates)}"
    )
    lines.append("")

    # Modernization audit
    lines.append("## Modernization status")
    lines.append("")
    lines.append("| Artifact | Present? |")
    lines.append("|---|:---:|")
    for display, rel, kind in ARTIFACTS:
        present = _check_artifact(app_dir, rel, kind)
        lines.append(f"| {display} | {'yes' if present else 'no'} |")
    lines.append("")

    # Existing probes
    probes = _list_existing_probes(app_dir)
    lines.append("## Existing probes (`check_*.py`)")
    lines.append("")
    for scope in ("malicious_app", "remote_attacker"):
        items = probes.get(scope) or []
        lines.append(f"### {scope}")
        if not items:
            lines.append("")
            lines.append("_(none)_")
            lines.append("")
            continue
        lines.append("")
        for name in items:
            lines.append(f"- `{name}`")
        lines.append("")

    # Synthetic vulnerabilities
    vulns = _list_synth_vulns(app_dir)
    lines.append("## Synthetic vulnerabilities")
    lines.append("")
    if not vulns:
        lines.append("_(none)_")
    else:
        for v in vulns:
            md = app_dir / "synthetic_vulnerabilities" / v / "metadata.json"
            extra = ""
            if md.is_file():
                try:
                    meta = json.loads(md.read_text(encoding="utf-8"))
                    parts = [
                        meta.get("title", ""),
                        f"CWE: {meta.get('cwe_id', '?')}",
                        f"CVE: {meta.get('historic_cve', '?')}",
                        f"attacker_model: {meta.get('attacker_model', '?')}",
                    ]
                    extra = " — " + " | ".join(p for p in parts if p)
                except Exception:
                    extra = " — (metadata unreadable)"
            lines.append(f"- `{v}`{extra}")
    lines.append("")

    # CVE coverage preview
    enriched_paths = sorted(
        (repo_root / "experimental").glob("android_*_enriched.jsonl")
    )
    if enriched_paths:
        all_cves = load_enriched_dataset(enriched_paths)
        relevant = filter_by_archetype_cwes(all_cves, profile.cwe_focus)
        matrix = build_coverage_matrix(relevant, [], [])  # no invariants → all gaps
        gaps = sum(1 for r in matrix if r.gap)
        top_gaps = sorted(
            [r for r in matrix if r.gap],
            key=lambda r: -(r.cve.base_score or 0.0),
        )[:8]
        lines.append("## CVE coverage preview")
        lines.append("")
        lines.append(
            f"In-scope (archetype CWE-matched) CVEs: **{len(relevant)}**. "
            f"Without any invariants in the suite, all are gaps. "
            f"Top by base score:"
        )
        lines.append("")
        lines.append("| CVE | CWEs | Severity | Score |")
        lines.append("|---|---|---|---:|")
        for r in top_gaps:
            cwes = ", ".join(r.cve.cwe_ids) or "—"
            sev = r.cve.severity or "—"
            score = f"{r.cve.base_score:.1f}" if r.cve.base_score is not None else "—"
            lines.append(f"| {r.cve.cve_id} | {cwes} | {sev} | {score} |")
        lines.append("")
        lines.append(
            f"_({gaps} total gaps; full matrix via "
            f"`generate_coverage_matrix.py --app {app}`.)_"
        )
        lines.append("")

    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--app", required=True)
    p.add_argument(
        "--out",
        default=None,
        help="Output dir (default: probe_gen/runs/app_status_<app>_<ts>)",
    )
    args = p.parse_args(argv)

    if args.app not in list_known_apps():
        print(
            f"[status] unknown app: {args.app!r}. Tagged apps: "
            f"{', '.join(list_known_apps())}",
            file=sys.stderr,
        )
        return 2

    repo_root = _REPO_ROOT
    app_dir = repo_root / "apps" / args.app
    if not app_dir.is_dir():
        print(f"[status] app dir not found: {app_dir}", file=sys.stderr)
        return 2

    if args.out:
        out_dir = Path(args.out)
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = repo_root / "probe_gen" / "runs" / f"app_status_{args.app}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    md = render_status_md(args.app, app_dir, repo_root)
    md_path = out_dir / "app_status.md"
    md_path.write_text(md, encoding="utf-8")
    print(f"[status] md={md_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
