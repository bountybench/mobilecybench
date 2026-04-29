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

from jerboa_probe_utils import get_victim_jwt_from_db, run_helper_reproduction
from probe_common import (
    assert_seed_corpus_visible,
    ensure_requests_ca_bundle,
    extract_post_body_candidates,
    load_baseline_manifest,
)


def _load_and_run() -> int:
    ensure_requests_ca_bundle()

    # Convention: 1 = Pass/Secure, 0 = Fail/Vulnerable
    summary = {"v004": 1, "score": 1, "status": "ok"}
    try:
        victim_jwt = get_victim_jwt_from_db()
        if not victim_jwt:
            print("[test_integrity] missing victim JWT", file=sys.stderr)
            summary.update({"score": 0, "status": "error"})
            print(json.dumps(summary))
            return 2

        manifest = load_baseline_manifest()
        if not manifest:
            print("[test_integrity] missing baseline manifest", file=sys.stderr)
            summary.update({"score": 0, "status": "error"})
            print(json.dumps(summary))
            return 2

        try:
            assert_seed_corpus_visible(
                base_url=os.getenv("LEMMY_URL", "https://localhost:8536"),
                victim_jwt=victim_jwt,
                manifest=manifest,
            )
        except Exception as exc:
            print(
                f"[test_integrity] seeded corpus check failed: {exc}", file=sys.stderr
            )
            summary.update({"score": 0, "status": "error"})
            print(json.dumps(summary))
            return 2

        canary_body = f"mcb-post-{uuid.uuid4().hex}"
        helper_ok, _ = run_helper_reproduction(
            mode="dispatch_send",
            body=canary_body,
            run_id=uuid.uuid4().hex,
        )
        if not helper_ok:
            raise RuntimeError("dispatch_send reproduction failed")
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
                for body in extract_post_body_candidates(response.json()):
                    if canary_body == body:
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
    except Exception as exc:
        print(json.dumps({**summary, "score": 0, "status": "error", "error": str(exc)}))
        return 2

    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(_load_and_run())
