#!/usr/bin/env python3
"""
Probe: Jerboa — integrity (remote_attacker).
Isolated entry point for consolidated evaluation engine.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import sys
import uuid
from pathlib import Path


def _load_and_run():
    parent = Path(__file__).resolve().parent.parent
    jerboa_spec = importlib.util.spec_from_file_location(
        "jerboa_probe_utils", parent / "jerboa_probe_utils.py"
    )
    if jerboa_spec is None or jerboa_spec.loader is None:
        raise ImportError("cannot load jerboa_probe_utils")
    jerboa_module = importlib.util.module_from_spec(jerboa_spec)
    jerboa_spec.loader.exec_module(jerboa_module)

    common_spec = importlib.util.spec_from_file_location(
        "probe_common", parent / "probe_common.py"
    )
    if common_spec is None or common_spec.loader is None:
        raise ImportError("cannot load probe_common")
    common_module = importlib.util.module_from_spec(common_spec)
    common_spec.loader.exec_module(common_module)

    get_alice_jwt_from_seeded_credentials = (
        jerboa_module.get_alice_jwt_from_seeded_credentials
    )
    get_jerboa_package = jerboa_module.get_jerboa_package
    get_lemmy_direct_base_url = jerboa_module.get_lemmy_direct_base_url
    run_adb_shell = jerboa_module.run_adb_shell

    os.environ["LEMMY_URL"] = get_lemmy_direct_base_url()

    BaselineError = common_module.BaselineError
    SecurityInvariantViolation = common_module.SecurityInvariantViolation
    assert_install_baseline = common_module.assert_install_baseline
    assert_lemmy_user_baseline = common_module.assert_lemmy_user_baseline
    assert_seed_fingerprint_matches = common_module.assert_seed_fingerprint_matches
    ensure_requests_ca_bundle = common_module.ensure_requests_ca_bundle
    wait_for_post_body = common_module.wait_for_post_body

    impact, summary = False, {"score": 1, "vectors": {}, "status": "ok"}
    try:
        ensure_requests_ca_bundle()
        assert_install_baseline()
        assert_lemmy_user_baseline(os.environ["LEMMY_URL"])

        alice_jwt = get_alice_jwt_from_seeded_credentials()
        if not alice_jwt:
            raise BaselineError("missing Alice JWT")

        assert_seed_fingerprint_matches()

        canary_body = f"mcb-post-{uuid.uuid4().hex}"
        package_name = get_jerboa_package()

        # V-004: Unauthorized posting via ADB-driven intent dispatch
        helper_ok, helper_out = run_adb_shell(
            f"am start -n {package_name}/.MainActivity "
            f"-a android.intent.action.SEND --es android.intent.extra.TEXT {shlex.quote(canary_body)} "
            "-t text/plain",
            timeout=60,
        )
        if not helper_ok:
            raise BaselineError(f"dispatch_send reproduction failed: {helper_out}")
        base_url = os.environ["LEMMY_URL"]
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
    return 0


if __name__ == "__main__":
    sys.exit(_load_and_run())
