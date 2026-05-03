#!/usr/bin/env python3
"""Audit per-app probe-layout maturity against the canonical HA layout.

For each app under ``apps/``, report which artifacts of the modernized probe
architecture are present:

  - threat_model.md
  - checks/ directory (with check_*.py files)
  - probe_lib.py / probe_common.py
  - seed_baseline.py
  - remote_attacker/ subtree
  - probe_config_rationale.md
  - probe_test_plan.md
  - synthetic vulnerability count

Output as JSON + Markdown. Used by Phase 1 onboarding to size the modernization
gap per app (canonical reference: ``apps/home-assistant-android/``).

Usage::

    python probe_gen/scripts/audit_app_layout.py [--apps-dir apps] [--out probe_gen/runs/audit_<ts>]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Each row: (display name, relative path under apps/<app>/, kind)
# kind = "file" | "dir-with-files" | "dir-count"
ARTIFACTS: list[tuple[str, str, str]] = [
    ("threat_model.md", "threat_model.md", "file"),
    ("checks/", "checks", "dir-with-files"),
    ("probe_lib.py", "probe_lib.py", "file"),
    ("probe_common.py", "probe_common.py", "file"),
    ("seed_baseline.py", "seed_baseline.py", "file"),
    ("remote_attacker/", "remote_attacker", "dir-with-files"),
    ("probe_config_rationale.md", "probe_config_rationale.md", "file"),
    ("probe_test_plan.md", "probe_test_plan.md", "file"),
    ("synthetic_vulnerabilities/", "synthetic_vulnerabilities", "dir-count"),
    ("test_access_control.py", "test_access_control.py", "file"),
    ("test_availability.py", "test_availability.py", "file"),
    ("test_confidentiality.py", "test_confidentiality.py", "file"),
    ("test_integrity.py", "test_integrity.py", "file"),
]

# Artifacts that, taken together, define the "modernized" layout.
# Apps missing these have the most pipeline work to do.
MODERNIZED_KEY = {
    "threat_model.md",
    "checks/",
    "seed_baseline.py",
    "remote_attacker/",
    "probe_config_rationale.md",
    "probe_test_plan.md",
}


def _check_artifact(app_dir: Path, rel: str, kind: str) -> dict:
    p = app_dir / rel
    if kind == "file":
        present = p.is_file()
        size = p.stat().st_size if present else 0
        return {"present": present, "size_bytes": size}
    if kind == "dir-with-files":
        present = p.is_dir() and any(p.iterdir())
        count = sum(1 for _ in p.iterdir()) if p.is_dir() else 0
        return {"present": present, "child_count": count}
    if kind == "dir-count":
        if not p.is_dir():
            return {"present": False, "child_count": 0}
        # Count immediate subdirs that look like vuln_*
        children = [c for c in p.iterdir() if c.is_dir()]
        return {"present": len(children) > 0, "child_count": len(children)}
    raise ValueError(f"unknown kind: {kind}")


def audit_app(app_dir: Path) -> dict:
    artifacts: dict[str, dict] = {}
    for display, rel, kind in ARTIFACTS:
        artifacts[display] = _check_artifact(app_dir, rel, kind)

    modernized_present = sum(
        1 for k in MODERNIZED_KEY if artifacts.get(k, {}).get("present")
    )
    modernized_total = len(MODERNIZED_KEY)
    # `probe_lib.py` OR `probe_common.py` counts as helpers
    has_helpers = (
        artifacts["probe_lib.py"]["present"] or artifacts["probe_common.py"]["present"]
    )

    return {
        "app": app_dir.name,
        "artifacts": artifacts,
        "modernized_score": f"{modernized_present}/{modernized_total}",
        "modernized_pct": round(100.0 * modernized_present / modernized_total, 1),
        "has_helpers": has_helpers,
        "synthetic_vuln_count": artifacts["synthetic_vulnerabilities/"]["child_count"],
    }


def audit_all(apps_dir: Path) -> list[dict]:
    results: list[dict] = []
    for app_path in sorted(apps_dir.iterdir()):
        if not app_path.is_dir():
            continue
        if app_path.name.startswith("."):
            continue
        # Skip dirs that don't look like apps
        if not (app_path / "metadata.json").is_file():
            continue
        results.append(audit_app(app_path))
    return results


def render_markdown(results: list[dict]) -> str:
    lines: list[str] = []
    lines.append("# App probe-layout maturity audit")
    lines.append("")
    lines.append(
        "Modernized score = count of canonical artifacts present "
        f"out of {len(MODERNIZED_KEY)}: " + ", ".join(sorted(MODERNIZED_KEY)) + "."
    )
    lines.append("")
    lines.append("Sorted by modernization completeness, descending.")
    lines.append("")
    headers = [
        "App",
        "Score",
        "%",
        "threat_model",
        "checks/",
        "helpers",
        "seed_baseline",
        "remote_attacker/",
        "rationale",
        "test_plan",
        "synth vulns",
    ]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    sorted_results = sorted(results, key=lambda r: (-r["modernized_pct"], r["app"]))
    for r in sorted_results:
        row = [
            r["app"],
            r["modernized_score"],
            f"{r['modernized_pct']:.0f}",
            "✓" if r["artifacts"]["threat_model.md"]["present"] else "✗",
            "✓" if r["artifacts"]["checks/"]["present"] else "✗",
            "✓" if r["has_helpers"] else "✗",
            "✓" if r["artifacts"]["seed_baseline.py"]["present"] else "✗",
            "✓" if r["artifacts"]["remote_attacker/"]["present"] else "✗",
            "✓" if r["artifacts"]["probe_config_rationale.md"]["present"] else "✗",
            "✓" if r["artifacts"]["probe_test_plan.md"]["present"] else "✗",
            str(r["synthetic_vuln_count"]),
        ]
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.append("## Per-app modernization gap")
    lines.append("")
    for r in sorted_results:
        missing = [
            k for k in sorted(MODERNIZED_KEY) if not r["artifacts"][k]["present"]
        ]
        if not missing:
            continue
        lines.append(f"- **{r['app']}** missing: {', '.join(missing)}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument(
        "--apps-dir",
        default=None,
        help="Path to apps/ (default: <repo_root>/apps).",
    )
    p.add_argument(
        "--out",
        default=None,
        help="Output directory (default: probe_gen/runs/audit_<ts>).",
    )
    args = p.parse_args(argv)

    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent.parent
    apps_dir = Path(args.apps_dir) if args.apps_dir else (repo_root / "apps")
    if not apps_dir.is_dir():
        print(f"[audit] apps dir not found: {apps_dir}", file=sys.stderr)
        return 2

    if args.out:
        out_dir = Path(args.out)
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = repo_root / "probe_gen" / "runs" / f"audit_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    results = audit_all(apps_dir)

    summary = {
        "schema_version": 1,
        "apps_dir": str(apps_dir),
        "app_count": len(results),
        "results": results,
    }
    (out_dir / "audit.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / "audit.md").write_text(render_markdown(results), encoding="utf-8")

    print(f"[audit] apps={len(results)}", file=sys.stderr)
    print(f"[audit] json={out_dir/'audit.json'}", file=sys.stderr)
    print(f"[audit] md={out_dir/'audit.md'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
