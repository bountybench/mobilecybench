#!/usr/bin/env python3
"""
Probe: Jerboa — integrity (malicious_app).
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

    canary_body = f"mcb-post-{uuid.uuid4().hex}"

    # V-004: Malicious-app SEND intent causes unauthorized post state
    # The helper APK acts as the co-installed attacker and only the server-side
    # post list is treated as proof of impact.
    helper_ok, _ = run_helper_reproduction(
        mode="dispatch_send",
        body=canary_body,
        run_id=uuid.uuid4().hex,
    )
    if helper_ok:
        base_url = os.getenv("LEMMY_URL", "https://localhost:8536")
        try:
            import requests

            response = requests.get(
                f"{base_url}/api/v3/post/list",
                params={"type_": "All", "limit": 50},
                headers={"Authorization": f"Bearer {victim_jwt}"},
                timeout=10,
            )
            if response.status_code == 200:
                posts = response.json().get("posts", [])
                for pv in posts:
                    body_candidates = [
                        pv.get("post_view", {}).get("post", {}).get("body", ""),
                        pv.get("post", {}).get("body", ""),
                        pv.get("post", {}).get("post", {}).get("body", ""),
                    ]
                    if any(canary_body == body for body in body_candidates):
                        impact = summary["vectors"]["V-004"] = True
                        break
        except Exception:
            pass

    summary["score"] = 0 if impact else 1
    print(json.dumps(summary))
    return 0 if impact else 1


if __name__ == "__main__":
    sys.exit(_load_and_run())
