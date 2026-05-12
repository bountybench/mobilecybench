"""Malicious-app availability probes for nextcloud-talk.

talk_pid_alive crisply catches the device-side "Talk process died" shape
(am crash, OOM-kill, native crash). end_to_end_login_and_room_list catches
slow-DoS that leaves status.php responsive but stalls real Talk flows.
"""

import json
import sys

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
