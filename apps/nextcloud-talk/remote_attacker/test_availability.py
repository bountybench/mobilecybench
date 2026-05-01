"""Remote-attacker availability probes for nextcloud-talk.

Server-side + host-side invariants only: server reachable, containers
healthy, spreed API serving, end-to-end login budget. Device-side
``talk_pid_alive`` is MA-only — RA's flow re-launches Talk via
``prepare_victim.sh`` between exploit and probes, so the PID check
cannot witness an RA-induced crash.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import common_setup as cs

if __name__ == "__main__":
    tests = [
        cs.server_dos,
        cs.check_container_health,
        cs.spreed_api_available,
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
