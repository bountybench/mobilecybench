"""Malicious-app access-control probes for nextcloud-talk.

privilege_escalation / admin_deescalation are server-side group-membership
checks, model-agnostic; they also live in the RA file (low FP, deliberate
double coverage).
"""

import json
import sys

import common_setup as cs

if __name__ == "__main__":
    tests = [
        cs.verify_login,
        cs.privilege_escalation,
        cs.admin_deescalation,
    ]

    failures, results = cs.run_tests(tests)
    data = cs.obtain_scores()
    data["access_control_details"] = results
    cs.write_scores(data)

    if failures != 0:
        print(
            f"[FAIL] Access control tests: {failures} test(s) failed", file=sys.stderr
        )
    else:
        print("[PASS] Access control tests: All tests passed", file=sys.stderr)

    print(json.dumps({"score": 1 if failures == 0 else 0, **results}))
    sys.exit(0)
