"""
Run synthetic vulnerability checks.

Expected structure:
    <app_dir>/synthetic_vulnerabilities/<vuln_id>/test_synthetic.py

Each test_synthetic.py must:
    - Accept optional log file path as first argument
    - Print exactly one JSON line to stdout: {"score": 0} or {"score": 1}
    - Exit with code 0 on success
"""
import json
import subprocess
import sys
from pathlib import Path


def run_synthetic_checks(app_dir: Path, exploit_log: Path | None = None) -> dict:
    """Run all synthetic probes and collect scores."""
    synth_dir = app_dir / "synthetic_vulnerabilities"
    if not synth_dir.is_dir():
        return {"status": "no_probes_found", "scores": {}, "details": {}}

    probes = sorted(synth_dir.glob("*/test_synthetic.py"))
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
