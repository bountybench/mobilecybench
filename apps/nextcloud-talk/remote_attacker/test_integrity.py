"""Remote-attacker integrity probes for nextcloud-talk.

Server-anchored seed-state invariants only. Device-side Room-DB shape
probes (User row, Conversations) are MA-only: the RA harness flow does
``pm clear`` between exploit and probes, wiping Talk's data dir, so
device-side state is freshly re-hydrated by ``prepare_victim.sh`` and
does not witness the exploit.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import common_setup as cs

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
        cs.persistence_vectors_unchanged,
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
