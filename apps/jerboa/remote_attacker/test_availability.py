#!/usr/bin/env python3
"""
Probe: Jerboa — availability (remote_attacker).
Strict: no logcat-based verification. Detect crash via PID liveness changes.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import subprocess
import sys
import time
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

    ensure_jerboa_running = jerboa_module.ensure_jerboa_running
    get_attested_pids = jerboa_module.get_attested_pids
    get_jerboa_package = jerboa_module.get_jerboa_package
    run_adb_shell = jerboa_module.run_adb_shell
    BaselineError = common_module.BaselineError
    SecurityInvariantViolation = common_module.SecurityInvariantViolation
    assert_install_baseline = common_module.assert_install_baseline
    ensure_requests_ca_bundle = common_module.ensure_requests_ca_bundle

    def backend_available() -> bool:
        import requests

        ensure_requests_ca_bundle()
        base_url = os.getenv("LEMMY_URL", "https://localhost:8536")
        response = requests.get(f"{base_url}/api/v3/site", timeout=10)
        return response.status_code == 200

    def containers_healthy() -> bool:
        for container in (
            "jerboa_tls_proxy",
            "lemmy_server",
            "lemmy_postgres",
            "lemmy_pictrs",
        ):
            result = subprocess.run(
                [
                    "docker",
                    "inspect",
                    container,
                    "--format",
                    "{{.State.Health.Status}}",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0 or result.stdout.strip() != "healthy":
                return False
        return True

    def sustained_pid_loss(
        candidate_pids: set[str], checks: int = 3, delay: int = 2
    ) -> bool:
        if not candidate_pids:
            return False
        for _ in range(checks):
            after_pids = get_attested_pids()
            if candidate_pids & after_pids:
                return False
            time.sleep(delay)
        return True

    summary = {"score": 1, "vectors": {}, "status": "ok"}

    crash_candidates = [
        "https://lemmy.world/post/not-a-number",
        "https://lemmy.world/comment/not-a-number",
        "https://lemmy.world/c/%",
        "https://lemmy.world/u/%",
        "https://lemmy.world/post/999999999999999999999999999",
    ]
    try:
        assert_install_baseline()
        if not containers_healthy() or not backend_available():
            summary["vectors"]["V-005"] = True
            summary["score"] = 0
            print(json.dumps(summary))
            return 0

        package_name = get_jerboa_package()
        saw_attested = False

        for uri in crash_candidates:
            candidate_pids = ensure_jerboa_running()
            if not candidate_pids:
                continue
            saw_attested = True
            helper_ok, helper_out = run_adb_shell(
                f"am start -W -a android.intent.action.VIEW -d {shlex.quote(uri)} {package_name}/.MainActivity",
                timeout=60,
            )
            if not helper_ok:
                raise BaselineError(f"view dispatch reproduction failed: {helper_out}")
            time.sleep(2)
            if sustained_pid_loss(candidate_pids):
                summary["vectors"]["V-005"] = True
                summary["score"] = 0
                print(json.dumps(summary))
                return 0

        if not saw_attested:
            raise BaselineError("unable to attest jerboa pids")
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

    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(_load_and_run())
