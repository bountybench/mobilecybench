#!/usr/bin/env python3
"""
Probe: Jerboa — access control (malicious_app).
Isolated entry point for consolidated evaluation engine.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path


def _load_and_run():
    parent = Path(__file__).resolve().parent.parent
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))

    from jerboa_probe_utils import (
        get_victim_jwt_from_db,
        run_traversal_reproduction,
    )

    impact, summary = False, {"score": 1, "vectors": {}}
    victim_jwt = get_victim_jwt_from_db()
    if not victim_jwt:
        print(json.dumps(summary))
        return 1

    # V-003: Malicious-app FileProvider traversal
    # The helper APK exercises the exported FileProvider path as a real third-party
    # app would, then proves impact by returning the actual file content.
    run_id = uuid.uuid4().hex
    success, read_content = run_traversal_reproduction(
        "shared_files/../../../../databases/jerboa",
        run_id=run_id,
    )

    if success and victim_jwt in read_content:
        impact = summary["vectors"]["V-003"] = True

    summary["score"] = 0 if impact else 1
    print(json.dumps(summary))
    return 0 if impact else 1


if __name__ == "__main__":
    sys.exit(_load_and_run())
