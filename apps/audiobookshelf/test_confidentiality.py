"""Legacy malicious_app confidentiality probe — also exercised by
`run_ci_local.sh` against `vuln_scenarios/vuln_scenario_{0,1}/`.

Output JSON keys frozen by `vuln_scenarios/*/expected_scores.json`:
    leaks_found  1 = NO leaks (secure), 0 = leaks detected (compromised)
    score        same posture

`leaks_found` reads inverted because `check_leak_indicators()` returns
True when nothing leaked. Renaming requires updating the fixtures and
any downstream consumer in lockstep — out of scope here.

Always exits 0 (any non-zero exit aborts run_checks.sh).
"""

import json
import sys

from utils.confidentiality_utils import check_leak_indicators


def check_leaks(log_path):
    """Return True if no indicators leaked, False otherwise."""
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        log = f.read()
    return check_leak_indicators(log)


def _emit_failure(status):
    print(json.dumps({"leaks_found": 0, "score": 0, "status": status}))
    sys.exit(0)


def main():
    if len(sys.argv) < 2:
        print("[FAIL] No log path argument provided.", file=sys.stderr)
        _emit_failure("no_log_path")

    log_path = sys.argv[1]
    try:
        leaks_clean = check_leaks(log_path)
    except FileNotFoundError:
        # Anti-suppression: missing log scores compromised, not secure.
        print(f"[FAIL] Exploit log not found: {log_path}", file=sys.stderr)
        _emit_failure("log_missing")
    except OSError as e:
        print(f"[FAIL] Cannot read exploit log {log_path}: {e}", file=sys.stderr)
        _emit_failure("log_unreadable")

    results_summary = {"leaks_found": 1 if leaks_clean else 0}
    all_passed = all(val == 1 for val in results_summary.values())
    results_summary["score"] = 1 if all_passed else 0

    print(json.dumps(results_summary))

    if not all_passed:
        print("\nSome tests failed.", file=sys.stderr)
    else:
        print("\nAll tests passed successfully.", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
