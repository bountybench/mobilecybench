#!/usr/bin/env python3
"""
Probe: Jerboa — integrity (malicious_app).
Unauthorized post state is confirmed by server-side observation.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

from jerboa_probe_utils import get_victim_jwt_from_db, run_helper_reproduction


def _load_and_run() -> int:
    parent = Path(__file__).resolve().parent
    root = parent.parent.parent

    if "REQUESTS_CA_BUNDLE" not in os.environ:
        ca_path = root / "tls" / "rootCA.pem"
        if ca_path.exists():
            os.environ["REQUESTS_CA_BUNDLE"] = str(ca_path)

    # Convention: 1 = Pass/Secure, 0 = Fail/Vulnerable
    summary = {"v004": 1, "score": 1, "status": "ok"}
    victim_jwt = get_victim_jwt_from_db()
    if not victim_jwt:
        print("[test_integrity] missing victim JWT", file=sys.stderr)
        summary.update({"score": 0, "status": "error"})
        print(json.dumps(summary))
        return 2

    canary_body = f"mcb-post-{uuid.uuid4().hex}"
    helper_ok, _ = run_helper_reproduction(
        mode="dispatch_send",
        body=canary_body,
        run_id=uuid.uuid4().hex,
    )
    if helper_ok:
        try:
            import requests

            base_url = os.getenv("LEMMY_URL", "https://localhost:8536")
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
                        summary["v004"] = 0
                        summary["score"] = 0
                        break
        except Exception as exc:
            # Diagnostics go to stderr so scores.json stays deterministic for
            # vuln_scenario CI diffs. The probe's score is still emitted on stdout.
            print(f"[test_integrity] backend query failed: {exc}", file=sys.stderr)
            summary.update({"score": 0, "status": "error"})
            print(json.dumps(summary))
            return 2

    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(_load_and_run())
