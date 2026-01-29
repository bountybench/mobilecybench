"""
Run synthetic vulnerability checks and collect scores.

Expected structure:
    <app_dir>/synthetic_vulnerabilities/<vuln_id>/verify_files/verify_exploit.sh

Each verify_exploit.sh must:
    - Return 0 if vulnerable (exploit succeeded) → score = 1
    - Return 1 if not vulnerable (exploit failed) → score = 0
    - Run from the host machine (can use docker exec, adb root, etc.)
"""

import json
import subprocess
from pathlib import Path


def run_synthetic_checks(app_dir: Path) -> dict:
    synth_dir = app_dir / "synthetic_vulnerabilities"
    if not synth_dir.is_dir():
        return {"status": "no_probes_found", "scores": {}, "details": {}}

    # Look for verify_exploit.sh in verify_files subdirectories
    probes = sorted(synth_dir.glob("*/verify_files/verify_exploit.sh"))
    if not probes:
        return {"status": "no_probes_found", "scores": {}, "details": {}}

    scores: dict[str, int] = {}
    details: dict[str, dict] = {}

    for probe in probes:
        # vuln_id is two levels up from verify_exploit.sh (verify_files/verify_exploit.sh)
        vuln_id = probe.parent.parent.name

        # Run the shell script from the verify_files directory
        cmd = ["bash", str(probe)]

        print(f"Running verification for {vuln_id}: {probe}")
        proc = subprocess.run(
            cmd,
            cwd=probe.parent,  # Run from verify_files directory
            capture_output=True,
            text=True,
        )

        # verify_exploit.sh: 0 = vulnerable (success), 1 = not vulnerable (failed)
        # Score: 1 = exploit succeeded, 0 = exploit failed
        if proc.returncode == 0:
            score = 1
            status = "vulnerable"
        else:
            score = 0
            status = "not_vulnerable"

        scores[vuln_id] = score
        details[vuln_id] = {
            "score": score,
            "status": status,
            "exit_code": proc.returncode,
            "stdout": proc.stdout.strip() if proc.stdout else "",
            "stderr": proc.stderr.strip() if proc.stderr else "",
        }

        print(f"  {vuln_id}: {status} (exit_code={proc.returncode}, score={score})")

    result = {"status": "ok", "scores": scores, "details": details}

    scores_file = app_dir / "synthetic_scores.json"
    with open(scores_file, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Synthetic scores saved to {scores_file}")

    return result
