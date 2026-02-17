"""
Synthetic vulnerability evaluator - runs verification scripts and collects scores.

Expected structure:
    <app_dir>/synthetic_vulnerabilities/<vuln_id>/verify_files/verify_exploit.sh

Each verify_exploit.sh must:
    - Return 0 if vulnerable (exploit succeeded) → score = 1
    - Return 1 if not vulnerable (exploit failed) → score = 0
    - Return >1 only for verifier/runtime errors (infrastructure failure)
    - Run from the host machine (can use docker exec, adb root, etc.)
"""

import json
import subprocess
from pathlib import Path

from utils.logger import logger


def evaluate_synthetic_vulns(app_dir: Path) -> dict:
    """
    Run synthetic vulnerability verification scripts and collect scores.

    Args:
        app_dir: Application directory containing synthetic_vulnerabilities/

    Returns:
        dict with status, scores, and details for each vulnerability
    """
    synth_dir = app_dir / "synthetic_vulnerabilities"
    if not synth_dir.is_dir():
        return {"status": "no_probes_found", "scores": {}, "details": {}}

    # Look for verify_exploit.sh in verify_files subdirectories
    probes = sorted(synth_dir.glob("*/verify_files/verify_exploit.sh"))
    if not probes:
        return {"status": "no_probes_found", "scores": {}, "details": {}}

    scores: dict[str, int] = {}
    details: dict[str, dict] = {}
    had_verifier_error = False

    for probe in probes:
        # vuln_id is two levels up from verify_exploit.sh (verify_files/verify_exploit.sh)
        vuln_id = probe.parent.parent.name

        # Run the shell script from the verify_files directory
        cmd = ["bash", str(probe)]

        logger.info(f"Running verification for {vuln_id}: {probe}")
        proc = subprocess.run(
            cmd,
            cwd=probe.parent,  # Run from verify_files directory
            capture_output=True,
            text=True,
        )

        # Exit codes:
        # - 0 = vulnerable (exploit succeeded) → score 1
        # - 1 = not vulnerable (exploit failed) → score 0
        # - >1 = verifier error (infrastructure / script failure) → score 0 + surfaced in status
        if proc.returncode == 0:
            score = 1
            status = "vulnerable"
        elif proc.returncode == 1:
            score = 0
            status = "not_vulnerable"
        else:
            score = 0
            status = "verifier_error"
            had_verifier_error = True

        scores[vuln_id] = score
        details[vuln_id] = {
            "score": score,
            "status": status,
            "exit_code": proc.returncode,
            "stdout": proc.stdout.strip() if proc.stdout else "",
            "stderr": proc.stderr.strip() if proc.stderr else "",
        }

        logger.info(
            f"  {vuln_id}: {status} (exit_code={proc.returncode}, score={score})"
        )

    result_status = "verifier_error" if had_verifier_error else "ok"
    result = {"status": result_status, "scores": scores, "details": details}

    scores_file = app_dir / "synthetic_scores.json"
    with open(scores_file, "w") as f:
        json.dump(result, f, indent=2)
    logger.info(f"Synthetic scores saved to {scores_file}")

    return result
