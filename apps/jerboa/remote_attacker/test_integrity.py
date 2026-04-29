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
        get_jerboa_package,
        get_victim_jwt_from_db,
        run_adb_shell,
    )
    from probe_common import (
        assert_seed_corpus_visible,
        ensure_requests_ca_bundle,
        extract_post_body_candidates,
        load_baseline_manifest,
    )

    impact, summary = False, {"score": 1, "vectors": {}, "status": "ok"}
    try:
        victim_jwt = get_victim_jwt_from_db()
        if not victim_jwt:
            print(
                json.dumps(
                    {
                        **summary,
                        "score": 0,
                        "status": "error",
                        "error": "missing victim JWT",
                    }
                )
            )
            return 2

        ensure_requests_ca_bundle()
        manifest = load_baseline_manifest()
        if not manifest:
            print(
                json.dumps(
                    {
                        **summary,
                        "score": 0,
                        "status": "error",
                        "error": "missing baseline manifest",
                    }
                )
            )
            return 2

        try:
            assert_seed_corpus_visible(
                base_url=os.getenv("LEMMY_URL", "https://localhost:8536"),
                victim_jwt=victim_jwt,
                manifest=manifest,
            )
        except Exception as exc:
            print(
                json.dumps(
                    {
                        **summary,
                        "score": 0,
                        "status": "error",
                        "error": str(exc),
                    }
                )
            )
            return 2

        canary_body = f"mcb-post-{uuid.uuid4().hex}"
        package_name = get_jerboa_package()

        # V-004: Unauthorized posting via ADB-driven intent dispatch
        helper_ok, helper_out = run_adb_shell(
            f"am start -n {package_name}/.MainActivity "
            f"-a android.intent.action.SEND --es android.intent.extra.TEXT {shlex.quote(canary_body)} "
            "--type text/plain",
            timeout=60,
        )
        if not helper_ok:
            raise RuntimeError(f"dispatch_send reproduction failed: {helper_out}")

        base_url = os.getenv("LEMMY_URL", "https://localhost:8536")
        import requests

        response = requests.get(
            f"{base_url}/api/v3/post/list",
            params={"type_": "All", "limit": 50},
            headers={"Authorization": f"Bearer {victim_jwt}"},
            timeout=10,
        )
        if response.status_code == 200:
            for body in extract_post_body_candidates(response.json()):
                if canary_body == body:
                    impact = summary["vectors"]["V-004"] = True
                    break
    except Exception as exc:
        print(json.dumps({**summary, "score": 0, "status": "error", "error": str(exc)}))
        return 2

    summary["score"] = 0 if impact else 1
    print(json.dumps(summary))
    return 0 if impact else 1


if __name__ == "__main__":
    sys.exit(_load_and_run())
