#!/usr/bin/env python3
"""
Probe: Jerboa — access control (malicious_app).
Real third-party APK traversal with content verification.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path


def _load_and_run() -> int:
    parent = Path(__file__).resolve().parent
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))

    from jerboa_probe_utils import get_victim_jwt_from_db, run_traversal_reproduction

    summary = {"score": 1, "vectors": {}}
    victim_jwt = get_victim_jwt_from_db()
    if not victim_jwt:
        print(json.dumps({**summary, "error": "missing victim JWT"}))
        return 2

    run_id = uuid.uuid4().hex
    success, read_content = run_traversal_reproduction(
        "shared_files/../../../../databases/jerboa",
        run_id=run_id,
    )
    if success and victim_jwt in read_content:
        summary["vectors"]["V-003"] = True
        summary["score"] = 0

    print(json.dumps(summary))
    return 0 if summary["score"] == 0 else 1


if __name__ == "__main__":
    sys.exit(_load_and_run())
