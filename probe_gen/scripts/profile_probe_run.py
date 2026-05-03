#!/usr/bin/env python3
"""Profile a synthetic-vulnerability run end-to-end with timestamped phase markers.

Wraps `run_ci_local.sh --test-synthetic-vuln <vuln_id>` (or any compatible
command), tees stdout/stderr to a timestamped log, classifies lines into phases
via regex markers (see ``markers.json``), and emits a JSON + Markdown summary.

Designed for the Phase 0.1 login-bottleneck audit: identify which phase
(emulator boot / backend startup / victim login / initial sync / verification)
dominates total wall time, so we can decide between Tier 1 (AVD snapshot)
vs Tier 2 (programmatic auth) per ``probe_gen/DESIGN.md``.

Usage::

    python probe_gen/scripts/profile_probe_run.py \\
        --app conversations \\
        --vuln vuln_0 \\
        [--out probe_gen/runs/profile_<run_id>] \\
        [--markers probe_gen/scripts/markers.json] \\
        [--cmd 'bash run_ci_local.sh apps/conversations --test-synthetic-vuln vuln_0']

The last form lets you profile any command (not just the synthetic-vuln gate).
Stdlib-only — no third-party deps. Tested with Python 3.11+.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
CARRIAGE_RETURN_RE = re.compile(r".*\r(?!\n)")


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
    start_t: float  # seconds since process start
    end_t: Optional[float] = None
    line_count: int = 0

    @property
    def duration(self) -> float:
        if self.end_t is None:
            return 0.0
        return self.end_t - self.start_t


def _load_markers(path: Path) -> list[Marker]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[Marker] = []
    for m in data.get("markers", []):
        out.append(Marker(pattern=m["pattern"], phase=m["phase"]))
    return out


def _strip_ansi(s: str) -> str:
    return ANSI_ESCAPE_RE.sub("", s)


def _collapse_cr_overwrites(s: str) -> str:
    # If a line was rewritten with \r (no \n), keep only the final segment.
    while True:
        m = CARRIAGE_RETURN_RE.match(s)
        if not m:
            return s
        s = s[m.end() :]


def _pick_marker(line: str, markers: list[Marker]) -> Optional[Marker]:
    for m in markers:
        if m.compiled.search(line):
            return m
    return None


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


class _LineReader(threading.Thread):
    """Reads lines from a stream, ANSI-strips and timestamps them, calls a sink."""

    def __init__(self, stream, sink, stream_name: str, t0: float) -> None:
        super().__init__(daemon=True)
        self.stream = stream
        self.sink = sink
        self.stream_name = stream_name
        self.t0 = t0

    def run(self) -> None:
        try:
            for raw in iter(self.stream.readline, ""):
                if not raw:
                    break
                t = time.monotonic() - self.t0
                cleaned = _strip_ansi(_collapse_cr_overwrites(raw.rstrip("\n")))
                self.sink(t, self.stream_name, cleaned)
        finally:
            try:
                self.stream.close()
            except Exception:
                pass


def profile(cmd: list[str], cwd: Path, markers: list[Marker], out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "full.log"
    json_path = out_dir / "summary.json"
    md_path = out_dir / "summary.md"

    phases: list[PhaseSpan] = [PhaseSpan(name="pre_init", start_t=0.0)]
    lock = threading.Lock()

    t0 = time.monotonic()

    log_fp = log_path.open("w", encoding="utf-8")

    def sink(t: float, stream: str, line: str) -> None:
        with lock:
            log_fp.write(f"{t:9.3f} [{stream}] {line}\n")
            log_fp.flush()
            m = _pick_marker(line, markers)
            phases[-1].line_count += 1
            if m and m.phase != phases[-1].name:
                phases[-1].end_t = t
                phases.append(PhaseSpan(name=m.phase, start_t=t))

    print(f"[profile] start_time_iso={_now_iso()}", file=sys.stderr)
    print(f"[profile] cwd={cwd}", file=sys.stderr)
    print(f"[profile] cmd={shlex.join(cmd)}", file=sys.stderr)
    print(f"[profile] log={log_path}", file=sys.stderr)

    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    rd_out = _LineReader(proc.stdout, sink, "stdout", t0)
    rd_err = _LineReader(proc.stderr, sink, "stderr", t0)
    rd_out.start()
    rd_err.start()

    def _on_sigint(signum, frame):
        print("[profile] received SIGINT; terminating subprocess", file=sys.stderr)
        try:
            proc.terminate()
        except Exception:
            pass

    signal.signal(signal.SIGINT, _on_sigint)

    try:
        rc = proc.wait()
    finally:
        rd_out.join(timeout=2.0)
        rd_err.join(timeout=2.0)
        log_fp.close()

    end_t = time.monotonic() - t0
    phases[-1].end_t = end_t

    summary = _build_summary(
        cmd=cmd,
        cwd=cwd,
        rc=rc,
        total=end_t,
        phases=phases,
        log_path=log_path,
    )
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    md_path.write_text(_render_markdown(summary), encoding="utf-8")

    print(f"[profile] rc={rc} total={end_t:.1f}s", file=sys.stderr)
    print(f"[profile] summary_json={json_path}", file=sys.stderr)
    print(f"[profile] summary_md={md_path}", file=sys.stderr)

    return summary


def _build_summary(
    cmd: list[str],
    cwd: Path,
    rc: int,
    total: float,
    phases: list[PhaseSpan],
    log_path: Path,
) -> dict:
    by_phase: dict[str, float] = {}
    for p in phases:
        by_phase[p.name] = by_phase.get(p.name, 0.0) + p.duration

    sorted_phases = sorted(by_phase.items(), key=lambda kv: kv[1], reverse=True)

    return {
        "schema_version": 1,
        "command": shlex.join(cmd),
        "cwd": str(cwd),
        "return_code": rc,
        "total_seconds": round(total, 3),
        "log_path": str(log_path),
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
        "started_at_iso": _now_iso(),
    }


def _render_markdown(summary: dict) -> str:
    lines: list[str] = []
    lines.append("# Profile run summary")
    lines.append("")
    lines.append(f"- Command: `{summary['command']}`")
    lines.append(f"- Working dir: `{summary['cwd']}`")
    lines.append(f"- Return code: `{summary['return_code']}`")
    total = summary["total_seconds"]
    mins = int(total // 60)
    secs = int(total - mins * 60)
    lines.append(f"- Total wall time: **{total:.1f}s ({mins}m{secs:02d}s)**")
    lines.append(f"- Log: `{summary['log_path']}`")
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
    lines.append("## Heuristic recommendation")
    lines.append("")
    lines.append(_render_recommendation(summary))
    lines.append("")
    return "\n".join(lines)


def _render_recommendation(summary: dict) -> str:
    if not summary["by_phase_total_seconds"]:
        return "_No phase data captured. Check markers.json against the actual log._"
    top = summary["by_phase_total_seconds"][0]
    name = top["phase"]
    secs = top["duration_seconds"]
    pct = top["pct_of_total"]
    if name == "pre_init":
        return (
            "_Dominant phase is `pre_init` — markers did not match the early output. "
            "Update `markers.json` patterns based on the captured log._"
        )
    sync_like = {"start_runtime", "prepare_victim", "post_runtime_idle"}
    boot_like = {"build_mode_detected", "apk_build", "post_apk_build_idle"}
    msg = [f"Dominant phase is `{name}` ({secs:.1f}s, {pct:.1f}% of total)."]
    if name in sync_like:
        msg.append(
            "This phase covers boot + backend + app install + victim login + initial sync. "
            "AVD snapshot post-sync (Tier 1) is the right primary fix; programmatic auth alone "
            "(Tier 2) will not skip the sync portion."
        )
    elif name in boot_like:
        msg.append(
            "APK build is dominant — usually amortizable across runs by build caching, not "
            "by login-tier work."
        )
    elif name == "verification":
        msg.append(
            "Verifier dominates — investigate slow checks (network timeouts, settle waits) "
            "before tackling login latency."
        )
    else:
        msg.append(
            "Tier choice undetermined from this phase alone; review the timeline."
        )
    return " ".join(msg)


def _default_run_id(app: str, vuln: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # Sanitize: callers often pass paths like "synthetic_vulnerabilities/vuln_0"
    safe_vuln = vuln.replace("/", "__").replace("\\", "__")
    return f"profile_{app}_{safe_vuln}_{ts}"


def _resolve_bash() -> str:
    """Pick a bash compatible with the repo's CRLF-mixed shell scripts.

    On Windows, Python's subprocess may resolve plain ``bash`` to WSL's
    ``/usr/bin/bash``, which fails on Git Bash–authored scripts with CRLF
    line endings (``$'\\r': command not found``) and translates Windows paths
    to ``/mnt/c/...`` form (which then fails to resolve repo-relative
    helpers). Prefer Git Bash explicitly via ``shutil.which`` (which honors
    the user's PATH), falling back to plain ``bash`` for non-Windows hosts.
    """
    bash = shutil.which("bash")
    if bash:
        return bash
    return "bash"


def _build_default_cmd(repo_root: Path, app: str, vuln: str) -> list[str]:
    # Use a relative path (cwd is set to repo_root). Absolute Windows paths
    # with backslashes get mangled when passed through bash.
    return [
        _resolve_bash(),
        "run_ci_local.sh",
        f"apps/{app}",
        "--test-synthetic-vuln",
        vuln,
    ]


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--app", help="App directory name under apps/ (e.g. conversations)")
    p.add_argument("--vuln", help="Synthetic vuln id (e.g. vuln_0)")
    p.add_argument(
        "--cmd",
        help="Override command. Quoted shell string. Bypasses --app/--vuln.",
    )
    p.add_argument(
        "--cwd",
        default=None,
        help="Working directory (default: repo root inferred from this script's location).",
    )
    p.add_argument(
        "--out",
        default=None,
        help="Output directory for log + summaries (default: probe_gen/runs/<auto-id>).",
    )
    p.add_argument(
        "--markers",
        default=None,
        help="Path to markers.json (default: probe_gen/scripts/markers.json next to this script).",
    )
    args = p.parse_args(argv)

    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent.parent
    cwd = Path(args.cwd) if args.cwd else repo_root

    if args.cmd:
        cmd = shlex.split(args.cmd)
        run_id_app = "custom"
        run_id_vuln = "cmd"
    else:
        if not (args.app and args.vuln):
            p.error("must supply --app and --vuln, or --cmd")
        cmd = _build_default_cmd(repo_root, args.app, args.vuln)
        run_id_app = args.app
        run_id_vuln = args.vuln

    out_dir = (
        Path(args.out)
        if args.out
        else (
            repo_root / "probe_gen" / "runs" / _default_run_id(run_id_app, run_id_vuln)
        )
    )

    markers_path = Path(args.markers) if args.markers else (script_dir / "markers.json")
    if not markers_path.exists():
        print(f"[profile] markers file not found: {markers_path}", file=sys.stderr)
        return 2
    markers = _load_markers(markers_path)

    summary = profile(cmd=cmd, cwd=cwd, markers=markers, out_dir=out_dir)
    return summary.get("return_code", 0) or 0


if __name__ == "__main__":
    raise SystemExit(main())
