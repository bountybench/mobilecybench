"""
Run synthetic vulnerability checks and collect scores.

Expected structure:
    <app_dir>/synthetic_vulnerabilities/<vuln_id>/test_synthetic.py

Each test_synthetic.py must:
    - Accept optional log file path as first argument
    - Print JSON with "score" key (0 or 1) as the last line of stdout
    - Exit with code 0 on success (non-zero exit → score defaults to 0)
"""

import json
import subprocess
import sys
from pathlib import Path


def run_synthetic_checks(app_dir: Path, exploit_log: Path | None = None) -> dict:
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
            # Use last line only (like tail -1) to handle debug output
            stdout = proc.stdout.strip()
            last_line = stdout.split("\n")[-1].strip() if stdout else "{}"
            payload = json.loads(last_line) if last_line else {}
            score = payload.get("score", 0)
            if score not in (0, 1):
                score = 0
        except (json.JSONDecodeError, KeyError):
            scores[vuln_id] = 0
            details[vuln_id] = {"score": 0, "error": "invalid output"}
            continue

        scores[vuln_id] = score
        details[vuln_id] = payload

    result = {"status": "ok", "scores": scores, "details": details}

    scores_file = app_dir / "synthetic_scores.json"
    with open(scores_file, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Synthetic scores saved to {scores_file}")

    return result
