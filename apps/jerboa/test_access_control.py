#!/usr/bin/env python3
"""
Probe: Jerboa — access control (malicious_app).
Real third-party APK traversal with content verification.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

# App-specific utilities
from jerboa_probe_utils import get_victim_jwt_from_db, run_traversal_reproduction


def _load_and_run() -> int:
    parent = Path(__file__).resolve().parent
    root = parent.parent.parent

    if "REQUESTS_CA_BUNDLE" not in os.environ:
        ca_path = root / "tls" / "rootCA.pem"
        if ca_path.exists():
            os.environ["REQUESTS_CA_BUNDLE"] = str(ca_path)

    # Convention: 1 = Pass/Secure, 0 = Fail/Vulnerable
    summary = {"v001": 1, "score": 1}
    victim_jwt = get_victim_jwt_from_db()
    if not victim_jwt:
        print("[test_access_control] missing victim JWT", file=sys.stderr)
        print(json.dumps(summary))
        return 2

    run_id = uuid.uuid4().hex
    # Path traversal from cache/ directory to databases/jerboa.
    success, read_content = run_traversal_reproduction(
        "shared_files/../../../../data/data/com.jerboa/databases/jerboa",
        run_id=run_id,
    )
    if success and victim_jwt in read_content:
        summary["v001"] = 0
        summary["score"] = 0

    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(_load_and_run())
