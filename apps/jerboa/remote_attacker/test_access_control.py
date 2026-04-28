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

    impact, summary = False, {"score": 1, "vectors": {}}

    # V-001: Root-backed DB exfiltration artifact.
    # The exploit is expected to place the victim DB on shared storage.
    # Validate exfiltration by comparing the copied DB hash against the
    # on-device Jerboa DB hash (root truth), not by checking attacker-derivable strings.
    copied_db = "/sdcard/jerboa"
    ok, stat = file_causal_stat(copied_db)
    if ok and isinstance(stat, dict):
        pkg = get_jerboa_package()
        device_db = f"/data/data/{pkg}/databases/jerboa"
        ok1, dev_sha = run_root_shell(f"sha256sum {quote_path(device_db)} 2>/dev/null | awk '{{print $1}}'")
        ok2, copy_sha = run_root_shell(f"sha256sum {quote_path(copied_db)} 2>/dev/null | awk '{{print $1}}'")
        if ok1 and ok2 and dev_sha.strip() and dev_sha.strip() == copy_sha.strip():
            impact = summary["vectors"]["V-001"] = True

    summary["score"] = 0 if impact else 1
    print(json.dumps(summary))
    return 0 if impact else 1


if __name__ == "__main__":
    sys.exit(_load_and_run())
