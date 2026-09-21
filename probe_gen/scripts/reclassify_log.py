#!/usr/bin/env python3
"""Re-classify an existing ``full.log`` against an updated ``markers.json``.

Pairs with ``profile_probe_run.py``: when markers need tuning, re-running the
20-min CI is wasteful. This script re-derives phase totals from the captured
log without re-executing.

Usage::

    python probe_gen/scripts/reclassify_log.py \\
        --log probe_gen/runs/profile_<id>/full.log \\
        [--markers probe_gen/scripts/markers.json] \\
        [--out probe_gen/runs/profile_<id>]

Defaults to writing ``summary.json`` + ``summary.md`` next to the log.
Stdlib-only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Lines in full.log are formatted by profile_probe_run.py as:
#   "  T.TTT [stream] cleaned line content"
# where T.TTT is monotonic seconds since process start.
LOG_LINE_RE = re.compile(r"^\s*([\d.]+)\s+\[([^\]]+)\]\s?(.*)$")


@dataclass
class Marker:
    pattern: str
    phase: str
    compiled: re.Pattern = field(init=False)

    def __post_init__(self) -> None:
        self.compiled = re.compile(self.pattern)


@dataclass
class PhaseSpan:
    name: str
    start_t: float
    end_t: Optional[float] = None
    line_count: int = 0

    @property
    def duration(self) -> float:
        if self.end_t is None:
            return 0.0
        return self.end_t - self.start_t


def _load_markers(path: Path) -> list[Marker]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        Marker(pattern=m["pattern"], phase=m["phase"]) for m in data.get("markers", [])
    ]


def _pick_marker(line: str, markers: list[Marker]) -> Optional[Marker]:
    for m in markers:
        if m.compiled.search(line):
            return m
    return None


def reclassify(log_path: Path, markers: list[Marker]) -> dict:
    phases: list[PhaseSpan] = [PhaseSpan(name="pre_init", start_t=0.0)]
    last_t: float = 0.0
    total_lines = 0

    with log_path.open("r", encoding="utf-8") as fp:
        for raw in fp:
            m = LOG_LINE_RE.match(raw)
            if not m:
                continue
            t = float(m.group(1))
            content = m.group(3)
            last_t = t
            total_lines += 1
            phases[-1].line_count += 1

            hit = _pick_marker(content, markers)
            if hit and hit.phase != phases[-1].name:
                phases[-1].end_t = t
                phases.append(PhaseSpan(name=hit.phase, start_t=t))

    phases[-1].end_t = last_t

    by_phase: dict[str, float] = {}
    for p in phases:
        by_phase[p.name] = by_phase.get(p.name, 0.0) + p.duration

    sorted_phases = sorted(by_phase.items(), key=lambda kv: kv[1], reverse=True)
    total = last_t

    return {
        "schema_version": 1,
        "source_log": str(log_path),
        "total_seconds": round(total, 3),
        "total_lines": total_lines,
        "timeline": [
            {
                "phase": p.name,
                "start_seconds": round(p.start_t, 3),
                "end_seconds": round(p.end_t or total, 3),
                "duration_seconds": round(p.duration, 3),
                "line_count": p.line_count,
            }
            for p in phases
        ],
        "by_phase_total_seconds": [
            {
                "phase": name,
                "duration_seconds": round(secs, 3),
                "pct_of_total": round(100.0 * secs / total, 1) if total > 0 else 0.0,
            }
            for name, secs in sorted_phases
        ],
    }


def _render_markdown(summary: dict) -> str:
    lines: list[str] = []
    lines.append("# Re-classified profile summary")
    lines.append("")
    lines.append(f"- Source log: `{summary['source_log']}`")
    total = summary["total_seconds"]
    mins = int(total // 60)
    secs = int(total - mins * 60)
    lines.append(f"- Total wall time: **{total:.1f}s ({mins}m{secs:02d}s)**")
    lines.append(f"- Lines processed: {summary['total_lines']}")
    lines.append("")
    lines.append("## Phase totals (sorted by duration)")
    lines.append("")
    lines.append("| Phase | Duration (s) | % of total |")
    lines.append("|---|---:|---:|")
    for entry in summary["by_phase_total_seconds"]:
        lines.append(
            f"| {entry['phase']} | {entry['duration_seconds']:.1f} | {entry['pct_of_total']:.1f}% |"
        )
    lines.append("")
    lines.append("## Linear timeline")
    lines.append("")
    lines.append("| Phase | Start (s) | End (s) | Duration (s) | Lines |")
    lines.append("|---|---:|---:|---:|---:|")
    for entry in summary["timeline"]:
        lines.append(
            f"| {entry['phase']} | {entry['start_seconds']:.1f} | {entry['end_seconds']:.1f} | "
            f"{entry['duration_seconds']:.1f} | {entry['line_count']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument(
        "--log", required=True, help="Path to full.log from a prior profile run."
    )
    p.add_argument(
        "--markers",
        default=None,
        help="Path to markers.json (default: probe_gen/scripts/markers.json next to this script).",
    )
    p.add_argument(
        "--out",
        default=None,
        help="Output directory (default: directory containing the log file).",
    )
    args = p.parse_args(argv)

    log_path = Path(args.log).resolve()
    if not log_path.exists():
        print(f"[reclassify] log not found: {log_path}", file=sys.stderr)
        return 2

    script_dir = Path(__file__).resolve().parent
    markers_path = Path(args.markers) if args.markers else (script_dir / "markers.json")
    if not markers_path.exists():
        print(f"[reclassify] markers file not found: {markers_path}", file=sys.stderr)
        return 2
    markers = _load_markers(markers_path)

    out_dir = Path(args.out) if args.out else log_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = reclassify(log_path, markers)
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    (out_dir / "summary.md").write_text(_render_markdown(summary), encoding="utf-8")

    print(
        f"[reclassify] total={summary['total_seconds']:.1f}s lines={summary['total_lines']}",
        file=sys.stderr,
    )
    print(f"[reclassify] summary_json={out_dir/'summary.json'}", file=sys.stderr)
    print(f"[reclassify] summary_md={out_dir/'summary.md'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
