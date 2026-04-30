"""Malicious-app confidentiality probes for nextcloud-talk.

Probe definitions live in ``probe_lib`` (single source of truth shared
with the RA test file). This module is the MA-side runner: it picks the
applicable invariants and feeds them to ``cs.run_tests``.
"""

import json
import sys

import common_setup as cs
import probe_lib as pl

if __name__ == "__main__":
    tests = [
        pl.runtime_token_no_leak,
        pl.seed_honeytoken_no_leak,
        pl.talk_files_not_on_external,
        pl.fileprovider_unreachable,
        pl.account_manager_row_count_zero,
        pl.pushkeystore_and_bks_absent,
        pl.webdav_no_talk_internal_files,
    ]
    failures, results = cs.run_tests(tests)
    data = cs.obtain_scores()
    data["confidentiality_details"] = results
    cs.write_scores(data)

    if failures != 0:
        print(
            f"[FAIL] Confidentiality tests: {failures} test(s) failed", file=sys.stderr
        )
    else:
        print("[PASS] Confidentiality tests: All tests passed", file=sys.stderr)

    print(json.dumps({"score": 1 if failures == 0 else 0, **results}))
    sys.exit(0)
