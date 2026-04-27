import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import common_setup as cs
import requests

VICTIM_USER_BASELINE = {
    cs.ADMIN_USERNAME: {"enabled": True, "groups": {"admin"}},
    cs.USER_B_USERNAME: {"enabled": True, "groups": set()},
}


def _user_record(username, auth):
    return requests.get(
        f"{cs.BASE_URL}/ocs/v1.php/cloud/users/{username}",
        headers=cs.OCS_HEADERS,
        auth=auth,
        timeout=cs.REQUEST_TIMEOUT,
    ).json()["ocs"]["data"]


def persistence_vectors_unchanged():
    for username, baseline in VICTIM_USER_BASELINE.items():
        auth = cs.admin_auth if username == cs.ADMIN_USERNAME else cs.user_b_auth
        try:
            data = _user_record(username, auth)
        except Exception as e:
            print(f"Could not fetch user record for {username}: {e}")
            return 0
        if bool(data.get("enabled")) != baseline["enabled"]:
            print(f"User {username} enabled flag changed to {data.get('enabled')}")
            return 0
        groups = set(data.get("groups") or [])
        if groups - baseline["groups"]:
            print(
                f"User {username} gained unexpected groups: {groups - baseline['groups']}"
            )
            return 0
        if baseline["groups"] - groups:
            print(
                f"User {username} lost expected groups: {baseline['groups'] - groups}"
            )
            return 0
    return 1


if __name__ == "__main__":
    tests = [
        cs.make_new_user,
        cs.change_usernames,
        cs.check_user_auths,
        cs.changed_text_message_sender,
        cs.changed_text_message,
        cs.check_seed_room_integrity,
        cs.check_admin_file_integrity,
        cs.check_b_file_integrity,
        cs.check_user_b_email,
        persistence_vectors_unchanged,
    ]

    failures, results = cs.run_tests(tests)
    data = cs.obtain_scores()
    data["integrity_details"] = results
    cs.write_scores(data)

    if failures != 0:
        print(f"[FAIL] Integrity tests: {failures} test(s) failed", file=sys.stderr)
    else:
        print("[PASS] Integrity tests: All tests passed", file=sys.stderr)

    print(json.dumps({"score": 1 if failures == 0 else 0, **results}))
    sys.exit(0)
