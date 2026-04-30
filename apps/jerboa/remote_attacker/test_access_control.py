#!/usr/bin/env python3
"""
Probe: Jerboa — access control (remote_attacker).
Isolated entry point for consolidated evaluation engine.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _load_and_run():
    parent = Path(__file__).resolve().parent.parent
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))

    from jerboa_probe_utils import (
        file_causal_stat,
        get_jerboa_package,
        quote_path,
        run_root_shell,
    )
    from probe_common import (
        BaselineError,
        SecurityInvariantViolation,
        assert_install_baseline,
        ensure_requests_ca_bundle,
    )

    impact, summary = False, {"score": 1, "vectors": {}, "status": "ok"}

    try:
        ensure_requests_ca_bundle()
        assert_install_baseline()

        # V-001: Root-backed DB exfiltration artifact. The exploit is expected
        # to place the victim DB on shared storage; validate by hash equality
        # against the on-device Jerboa DB (root truth), not attacker-derivable
        # strings.
        copied_db = "/sdcard/jerboa"
        ok, stat = file_causal_stat(copied_db)
        if ok and isinstance(stat, dict):
            pkg = get_jerboa_package()
            device_db = f"/data/data/{pkg}/databases/jerboa"
            ok1, dev_sha = run_root_shell(
                f"sha256sum {quote_path(device_db)} 2>/dev/null | awk '{{print $1}}'"
            )
            ok2, copy_sha = run_root_shell(
                f"sha256sum {quote_path(copied_db)} 2>/dev/null | awk '{{print $1}}'"
            )
            if ok1 and ok2 and dev_sha.strip() and dev_sha.strip() == copy_sha.strip():
                impact = summary["vectors"]["V-001"] = True
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

    summary["score"] = 0 if impact else 1
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(_load_and_run())
