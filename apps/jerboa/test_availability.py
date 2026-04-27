#!/usr/bin/env python3
"""
Probe: Jerboa — availability (malicious_app).
Crash-side-effect probe driven by a co-installed helper APK.
"""

from __future__ import annotations

import json
import sys
import time
import uuid

from jerboa_probe_utils import (
    get_attested_pids,
    get_boot_time,
    get_device_time_info,
    parse_threadtime_epoch,
    parse_threadtime_line,
    run_helper_reproduction,
    run_root_shell,
)


def _load_and_run() -> int:
    # Convention: 1 = Pass/Secure, 0 = Fail/Vulnerable
    summary = {"v005": 1, "score": 1}

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
        run_root_shell("logcat -c")
        run_helper_reproduction(
            mode="dispatch_view",
            uri=uri,
            run_id=uuid.uuid4().hex,
        )
        time.sleep(2)

        year, tzinfo = get_device_time_info()
        boot_time = get_boot_time()
        helper_ok, crash_log = run_helper_reproduction(
            mode="read_logs",
            logcat_tag="AndroidRuntime",
            logcat_pattern="FATAL EXCEPTION",
            run_id=uuid.uuid4().hex,
        )
        if helper_ok and crash_log:
            fatal_pids: set[str] = set()
            process_pids: set[str] = set()
            for line in crash_log.splitlines():
                prefix, pid, _tag, msg, _ = parse_threadtime_line(line)
                if not pid or pid not in candidate_pids:
                    continue
                if year is not None and tzinfo is not None:
                    epoch = parse_threadtime_epoch(prefix or "", year, tzinfo)
                    if epoch is not None and epoch < boot_time:
                        continue
                if "FATAL EXCEPTION" in msg:
                    fatal_pids.add(pid)
                if "Process: com.jerboa" in msg:
                    process_pids.add(pid)

            if fatal_pids & process_pids:
                summary["v005"] = 0
                summary["score"] = 0
                break

    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(_load_and_run())
