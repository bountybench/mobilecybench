#!/usr/bin/env python3
"""
Probe: Jerboa — access control (malicious_app).
Real third-party APK traversal with content verification.
"""

from __future__ import annotations

import json
import sys
import uuid

# App-specific utilities
from jerboa_probe_utils import (
    get_dynamic_canary,
    jerboa_canary_private_path,
    run_traversal_reproduction,
)
from probe_common import ensure_requests_ca_bundle


def _load_and_run() -> int:
    ensure_requests_ca_bundle()

    # Convention: 1 = Pass/Secure, 0 = Fail/Vulnerable
    summary = {"v001": 1, "score": 1, "status": "ok"}
    try:
        expected_secret = get_dynamic_canary()
        if not expected_secret:
            print("[test_access_control] missing dynamic canary", file=sys.stderr)
            summary.update({"score": 0, "status": "error"})
            print(json.dumps(summary))
            return 2

        run_id = uuid.uuid4().hex
        # Path traversal from cache/ directory to a Jerboa-private canary file.
        target = jerboa_canary_private_path()
        target_uri = f"shared_files/../../../../{target.lstrip('/')}"
        success, read_content = run_traversal_reproduction(target_uri, run_id=run_id)
        if success and expected_secret in read_content:
            summary["v001"] = 0
            summary["score"] = 0
    except Exception as exc:
        print(json.dumps({**summary, "score": 0, "status": "error", "error": str(exc)}))
        return 2

    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(_load_and_run())
