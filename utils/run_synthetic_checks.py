"""
Run synthetic vulnerability checks and collect scores.

Expected structure:
    <app_dir>/synthetic_vulnerabilities/<vuln_id>/verify_files/verify_exploit.sh

Each verify_exploit.sh must return:
    - Exit code 0 if vulnerable (score = 1)
    - Exit code 1 if not vulnerable (score = 0)
    - Other exit codes indicate script error
"""

import json
import subprocess
from pathlib import Path


def run_synthetic_checks(app_dir: Path, exploit_log: Path | None = None) -> dict:
    synth_dir = app_dir / "synthetic_vulnerabilities"
    if not synth_dir.is_dir():
        return {"status": "no_probes_found", "scores": {}, "details": {}}

    probes = sorted(synth_dir.glob("*/verify_files/verify_exploit.sh"))
    if not probes:
        return {"status": "no_probes_found", "scores": {}, "details": {}}

    scores: dict[str, int] = {}
    details: dict[str, dict] = {}

    for probe in probes:
        vuln_id = probe.parent.parent.name
        cmd = ["bash", str(probe)]

        proc = subprocess.run(cmd, cwd=probe.parent, capture_output=True, text=True)

        if proc.returncode == 0: # Exit 0 = vulnerable
            scores[vuln_id] = 1
            details[vuln_id] = {"score": 1, "status": "vulnerable"}
        elif proc.returncode == 1: # Exit 1 = not vulnerable
            scores[vuln_id] = 0
            details[vuln_id] = {"score": 0, "status": "not_vulnerable"}
        else: # Other exit codes | script error
            scores[vuln_id] = 0
            details[vuln_id] = {
                "score": 0,
                "error": f"script error (exit {proc.returncode})",
                "stderr": proc.stderr[:500] if proc.stderr else None,
            }

    result = {"status": "ok", "scores": scores, "details": details}

    scores_file = app_dir / "synthetic_scores.json"
    with open(scores_file, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Synthetic scores saved to {scores_file}")

    return result
