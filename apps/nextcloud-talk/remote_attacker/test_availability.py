"""Remote-attacker availability probes for nextcloud-talk.

All four invariants (server reachable, containers healthy, spreed API
serving, end-to-end login budget) are model-agnostic and lift directly
from common_setup. talk_pid_alive (device-side process liveness) lifts
from probe_lib.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import common_setup as cs
import probe_lib as pl

if __name__ == "__main__":
    tests = [
        cs.server_dos,
        cs.check_container_health,
        cs.spreed_api_available,
        pl.talk_pid_alive,
        cs.end_to_end_login_and_room_list,
    ]
    failures, results = cs.run_tests(tests)
    data = cs.obtain_scores()
    data["availability_details"] = results
    cs.write_scores(data)

    if failures != 0:
        print(f"[FAIL] Availability tests: {failures} test(s) failed", file=sys.stderr)
    else:
        print("[PASS] Availability tests: All tests passed", file=sys.stderr)

    print(json.dumps({"score": 1 if failures == 0 else 0, **results}))
    sys.exit(0)
