"""Malicious-app integrity probes for nextcloud-talk.

Server-anchored seed-state probes (cs.*) plus device-side Room-DB shape
invariants (pl.*). Probe definitions live in ``probe_lib`` (shared with
the RA test file).
"""

import json
import sys

import common_setup as cs
import probe_lib as pl

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
        pl.user_row_identity_intact,
        pl.conversations_shape_intact,
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
