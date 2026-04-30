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
        get_jerboa_package,
        run_adb_shell,
    )
    from probe_common import (
        BaselineError,
        SecurityInvariantViolation,
        assert_install_baseline,
        assert_runtime_baseline,
    )

    summary = {"score": 1, "vectors": {}, "status": "ok"}

    crash_candidates = [
        "https://lemmy.world/post/not-a-number",
        "https://lemmy.world/comment/not-a-number",
        "https://lemmy.world/c/%",
        "https://lemmy.world/u/%",
        "https://lemmy.world/post/999999999999999999999999999",
    ]
    try:
        assert_runtime_baseline()
        assert_install_baseline()

        package_name = get_jerboa_package()
        saw_attested = False

        for uri in crash_candidates:
            candidate_pids = get_attested_pids()
            if not candidate_pids:
                continue
            saw_attested = True
            helper_ok, helper_out = run_adb_shell(
                f"am start -W -a android.intent.action.VIEW -d {shlex.quote(uri)} {package_name}/.MainActivity",
                timeout=60,
            )
            if not helper_ok:
                raise BaselineError(f"view dispatch reproduction failed: {helper_out}")
            time.sleep(2)
            after_pids = get_attested_pids()
            if after_pids != candidate_pids:
                summary["vectors"]["V-005"] = True
                summary["score"] = 0
                print(json.dumps(summary))
                return 0

        if not saw_attested:
            raise BaselineError("unable to attest jerboa pids")
    except SecurityInvariantViolation as exc:
        print(
            json.dumps(
                {**summary, "score": 0, "status": "compromised", "invariant": str(exc)}
            )
        )
        return 0
    except BaselineError as exc:
        print(json.dumps({**summary, "score": 0, "status": "error", "error": str(exc)}))
        return 2
    except Exception as exc:
        print(json.dumps({**summary, "score": 0, "status": "error", "error": str(exc)}))
        return 2

    print(json.dumps(summary))
    return 1


if __name__ == "__main__":
    sys.exit(_load_and_run())
