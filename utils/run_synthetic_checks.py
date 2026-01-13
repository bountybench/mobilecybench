#!/usr/bin/env python3
"""
Run synthetic vulnerability checks.

Expected structure:
    <app_dir>/synthetic_vulnerabilities/<vuln_id>/test_synthetic.py

Each test_synthetic.py must:
    - Accept optional log file path as first argument
    - Print exactly one JSON line to stdout: {"score": 0} or {"score": 1}
    - Exit with code 0 on success
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path


def discover_probes(app_dir: Path) -> list[Path]:
    """Find all test_synthetic.py files."""
    synth_dir = app_dir / "synthetic_vulnerabilities"
    if not synth_dir.is_dir():
        return []
    return sorted(synth_dir.glob("*/test_synthetic.py"))


def run_synthetic_checks(app_dir: Path, exploit_log: Path | None = None) -> dict:
    """Run all synthetic probes and collect scores."""
    probes = discover_probes(app_dir)
    if not probes:
        return {"status": "no_probes_found", "scores": {}, "details": {}}

    scores: dict[str, int] = {}
    details: dict[str, dict] = {}

    for probe in probes:
        vuln_id = probe.parent.name

        cmd = [sys.executable, str(probe)]
        if exploit_log:
            cmd.append(str(exploit_log))

        proc = subprocess.run(cmd, cwd=app_dir, capture_output=True, text=True)

        if proc.returncode != 0:
            scores[vuln_id] = 0
            details[vuln_id] = {"score": 0, "error": "non-zero exit"}
            continue

        try:
            payload = json.loads(proc.stdout.strip())
            score = payload["score"]
            assert score in (0, 1)
        except (json.JSONDecodeError, KeyError, AssertionError):
            scores[vuln_id] = 0
            details[vuln_id] = {"score": 0, "error": "invalid output"}
            continue

        scores[vuln_id] = score
        details[vuln_id] = payload

    return {"status": "ok", "scores": scores, "details": details}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run synthetic vulnerability checks")
    parser.add_argument("--app", required=True, help="Path to app directory")
    parser.add_argument("--log", default=None, help="Path to agent/exploit log")
    args = parser.parse_args(argv)

    app_dir = Path(args.app).expanduser().resolve()
    exploit_log = Path(args.log).expanduser().resolve() if args.log else None
    if exploit_log is not None and not exploit_log.is_file():
        exploit_log = None

    try:
        result = run_synthetic_checks(app_dir, exploit_log=exploit_log)
    except Exception:
        print(json.dumps({"status": "error", "scores": {}, "details": {}}))
        return 1

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
