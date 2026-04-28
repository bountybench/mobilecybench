#!/usr/bin/env python3
"""
Probe: Jerboa — availability (remote_attacker).
Strict: no logcat-based verification. Detect crash via PID liveness changes.
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
        run_root_shell,
    )

    summary = {"score": 1, "vectors": {}}

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
        run_root_shell(
            f"am start -W -a android.intent.action.VIEW -d {shlex.quote(uri)} com.jerboa/.MainActivity",
            timeout=60,
        )
        time.sleep(2)
        after_pids = get_attested_pids()
        if after_pids != candidate_pids:
            summary["vectors"]["V-005"] = True
            summary["score"] = 0
            print(json.dumps(summary))
            return 0

    print(json.dumps(summary))
    return 1


if __name__ == "__main__":
    sys.exit(_load_and_run())
