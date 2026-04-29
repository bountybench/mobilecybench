#!/usr/bin/env python3
"""
Probe: Jerboa — availability (malicious_app).
Strict: no logcat-based verification. Detect crash via PID liveness changes.
"""

from __future__ import annotations

import json
import sys
import time
import uuid

from jerboa_probe_utils import (
    get_attested_pids,
    run_helper_reproduction,
)


def _load_and_run() -> int:
    # Convention: 1 = Pass/Secure, 0 = Fail/Vulnerable
    summary = {"v005": 1, "score": 1, "status": "ok"}
    saw_attested = False

    crash_candidates = [
        "https://lemmy.world/post/not-a-number",
        "https://lemmy.world/comment/not-a-number",
        "https://lemmy.world/c/%",
        "https://lemmy.world/u/%",
        "https://lemmy.world/post/999999999999999999999999999",
    ]

    for uri in crash_candidates:
        candidate_pids = get_attested_pids()
        if not candidate_pids:
            continue
        saw_attested = True
        helper_ok, _ = run_helper_reproduction(
            mode="dispatch_view",
            uri=uri,
            run_id=uuid.uuid4().hex,
        )
        if not helper_ok:
            raise RuntimeError("view dispatch reproduction failed")
        time.sleep(2)

        after_pids = get_attested_pids()
        # A crash/restart will generally change the PID set or drop to empty briefly.
        if after_pids != candidate_pids:
            summary["v005"] = 0
            summary["score"] = 0
            break

    if not saw_attested:
        summary.update({"v005": 0, "score": 0, "status": "error"})

    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(_load_and_run())
