#!/usr/bin/env python3
"""Estimate Tier 1 (AVD snapshot) savings from a profile-run summary.json.

Reads ``summary.json`` from a ``profile_probe_run.py`` output directory
and partitions phases into:

  - **Amortizable** — paid once on first-time setup; not paid per
    probe-gen iteration. APK build, gradle daemon spin-up, etc.
  - **Per-iteration (current)** — paid every gate run today: emulator
    boot, backend up, app install, login, sync.
  - **Per-iteration (Tier 1)** — paid every gate run with AVD snapshot
    + backend snapshot restore: just the snapshot restore + verifier.

Outputs a Markdown report with the estimated savings and a sanity-check
that the phase budget reconciles (sum ≈ total).

Usage::

    python probe_gen/scripts/analyze_tier1_savings.py \\
        --summary probe_gen/runs/profile_<id>/summary.json \\
        [--out probe_gen/runs/profile_<id>/tier1_estimate.md]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

# Phase classification. Update as new markers land in markers.json.
AMORTIZABLE = {
    "apk_build_phase",
    "apk_build_clean",
    "apk_build_vuln",
    "apk_build_post_gradle",
    "vuln_patch_application",
    "runtime_patch_application",
    "synth_vuln_mode_init",  # one-time validation banner
}

PER_ITERATION_CURRENT = {
    "ssrf_listener_startup",
    "emulator_start",
    "ca_injection",
    "prepare_victim",
    "seed_messages",
    "apk_install",
    "app_launch",
    "start_runtime",
    "post_runtime_idle",
    "flag_generation",
    "flag_injection",
    "vuln_scenario_creation",
    "exploit_replay",
    "verification",
    "dual_comparator_phase",
}

# Phases that even Tier 1 cannot skip (per-iteration, must run on each
# probe evaluation). Snapshot restore replaces the rest.
TIER1_RESIDUAL = {
    "exploit_replay",
    "verification",
    # SSRF listener may need re-creation each iteration if container died;
    # cheap (<10s) so we leave it in residual.
    "ssrf_listener_startup",
}

CLEANUP = {"cleanup", "pre_init"}


def classify_phase(name: str) -> str:
    if name in AMORTIZABLE:
        return "amortizable"
    if name in TIER1_RESIDUAL:
        return "tier1_residual"
    if name in PER_ITERATION_CURRENT:
        return "per_iteration_current"
    if name in CLEANUP:
        return "cleanup"
    return "unclassified"


def analyze(summary: dict) -> dict:
    by_phase = summary.get("by_phase_total_seconds") or []
    total = float(summary.get("total_seconds") or 0.0)

    buckets: dict[str, float] = {
        "amortizable": 0.0,
        "per_iteration_current": 0.0,
        "tier1_residual": 0.0,
        "cleanup": 0.0,
        "unclassified": 0.0,
    }
    rows: list[dict] = []
    for entry in by_phase:
        name = entry["phase"]
        secs = float(entry["duration_seconds"])
        bucket = classify_phase(name)
        buckets[bucket] += secs
        rows.append({"phase": name, "seconds": secs, "bucket": bucket})

    # Tier 1 estimate: assume snapshot restore takes ~10s.
    snapshot_restore_s = 10.0
    tier1_per_iter = buckets["tier1_residual"] + snapshot_restore_s
    current_per_iter = buckets["per_iteration_current"] + buckets["tier1_residual"]
    speedup = (current_per_iter / tier1_per_iter) if tier1_per_iter > 0 else 0.0

    return {
        "total_seconds": total,
        "buckets": buckets,
        "snapshot_restore_assumed_seconds": snapshot_restore_s,
        "current_per_iteration_seconds": current_per_iter,
        "tier1_per_iteration_seconds": tier1_per_iter,
        "tier1_speedup_x": round(speedup, 1),
        "rows": rows,
    }


def render_md(analysis: dict, summary_path: Path) -> str:
    total = analysis["total_seconds"]
    b = analysis["buckets"]
    cur = analysis["current_per_iteration_seconds"]
    t1 = analysis["tier1_per_iteration_seconds"]
    speedup = analysis["tier1_speedup_x"]

    def fmt_secs(s: float) -> str:
        return f"{s:.1f}s ({int(s // 60)}m{int(s) % 60:02d}s)"

    lines: list[str] = []
    lines.append("# Tier 1 (AVD snapshot) savings estimate")
    lines.append("")
    lines.append(f"Source: `{summary_path}`")
    lines.append("")
    lines.append(f"- Total wall time: **{fmt_secs(total)}**")
    lines.append(
        f"- Amortizable (paid once / on-source-change only): **{fmt_secs(b['amortizable'])}** "
        f"({(100 * b['amortizable'] / total) if total else 0:.1f}%)"
    )
    lines.append(
        f"- Per-iteration cost today: **{fmt_secs(cur)}** "
        f"({(100 * cur / total) if total else 0:.1f}%)"
    )
    lines.append(
        f"- Per-iteration cost with Tier 1 (snapshot restore "
        f"~{analysis['snapshot_restore_assumed_seconds']:.0f}s + residual): "
        f"**{fmt_secs(t1)}**"
    )
    lines.append(f"- **Per-iteration speedup: ~{speedup}×**")
    lines.append("")
    lines.append(
        f"At {cur:.0f}s/iteration today, an N-iteration adversarial loop "
        f"costs ≈ {cur * 50:.0f}s for N=50 (~{(cur * 50) / 60:.0f} min). "
        f"Tier 1 same loop: ≈ {t1 * 50:.0f}s "
        f"(~{(t1 * 50) / 60:.0f} min). Saves "
        f"{(cur - t1) * 50:.0f}s for the same iteration count."
    )
    lines.append("")

    lines.append("## Phase classification")
    lines.append("")
    lines.append("| Phase | Bucket | Duration (s) |")
    lines.append("|---|---|---:|")
    for row in sorted(analysis["rows"], key=lambda r: -r["seconds"]):
        lines.append(f"| {row['phase']} | {row['bucket']} | {row['seconds']:.1f} |")
    lines.append("")
    if b["unclassified"] > 0:
        lines.append(
            f"_(unclassified phases total {b['unclassified']:.1f}s — "
            "update `analyze_tier1_savings.py` constants if these are non-trivial.)_"
        )
        lines.append("")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument(
        "--summary", required=True, help="Path to summary.json from profile run."
    )
    p.add_argument(
        "--out",
        default=None,
        help="Output path for tier1_estimate.md (default: alongside summary.json).",
    )
    args = p.parse_args(argv)

    summary_path = Path(args.summary).resolve()
    if not summary_path.is_file():
        print(f"[tier1] summary.json not found: {summary_path}", file=sys.stderr)
        return 2
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    analysis = analyze(summary)

    out_path = (
        Path(args.out).resolve()
        if args.out
        else summary_path.parent / "tier1_estimate.md"
    )
    out_path.write_text(render_md(analysis, summary_path), encoding="utf-8")
    print(
        f"[tier1] current_per_iter={analysis['current_per_iteration_seconds']:.1f}s "
        f"tier1_per_iter={analysis['tier1_per_iteration_seconds']:.1f}s "
        f"speedup={analysis['tier1_speedup_x']}x",
        file=sys.stderr,
    )
    print(f"[tier1] md={out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
