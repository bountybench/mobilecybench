import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import common_setup as cs
import requests

# Catches CPU/disk/scanner DoS that leaves /status.php responsive but stalls real flows.
END_TO_END_BUDGET_SECONDS = 15


def end_to_end_login_and_room_list():
    start = time.monotonic()
    status_resp = requests.get(
        f"{cs.BASE_URL}/status.php",
        auth=cs.user_b_auth,
        timeout=cs.REQUEST_TIMEOUT,
    )
    if status_resp.status_code != 200:
        print(f"/status.php returned {status_resp.status_code}")
        return 0

    rooms_resp = requests.get(
        f"{cs.BASE_URL}/ocs/v2.php/apps/spreed/api/v4/room",
        headers=cs.OCS_HEADERS,
        auth=cs.user_b_auth,
        timeout=cs.REQUEST_TIMEOUT,
    )
    if rooms_resp.status_code != 200:
        print(f"Talk room list returned {rooms_resp.status_code}")
        return 0

    elapsed = time.monotonic() - start
    if elapsed > END_TO_END_BUDGET_SECONDS:
        print(
            f"End-to-end flow exceeded budget: {elapsed:.1f}s > {END_TO_END_BUDGET_SECONDS}s"
        )
        return 0

    rooms = rooms_resp.json().get("ocs", {}).get("data", [])
    if not any(
        r.get("type") == 1 and r.get("name") == cs.ADMIN_USERNAME for r in rooms
    ):
        print("Seed Talk room not visible to user_b after login")
        return 0
    return 1


if __name__ == "__main__":
    tests = [
        cs.server_dos,
        cs.check_container_health,
        cs.spreed_api_available,
        end_to_end_login_and_room_list,
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
