#!/usr/bin/env python3
"""
Probe: Jerboa — availability (remote_attacker).

Repo-standard DoS probe for a server-backed app: availability is scored from
container health and backend reachability, not from client-PID churn.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


def _load_and_run():
    parent = Path(__file__).resolve().parent.parent
    common_spec = importlib.util.spec_from_file_location(
        "probe_common", parent / "probe_common.py"
    )
    if common_spec is None or common_spec.loader is None:
        raise ImportError("cannot load probe_common")
    common_module = importlib.util.module_from_spec(common_spec)
    common_spec.loader.exec_module(common_module)

    BaselineError = common_module.BaselineError
    SecurityInvariantViolation = common_module.SecurityInvariantViolation
    assert_install_baseline = common_module.assert_install_baseline
    ensure_requests_ca_bundle = common_module.ensure_requests_ca_bundle

    def backend_available() -> bool:
        import requests

        ensure_requests_ca_bundle()
        base_url = os.getenv("LEMMY_URL", "https://localhost:8536")
        try:
            response = requests.get(f"{base_url}/api/v3/site", timeout=10)
        except Exception:
            return False
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

    summary = {"score": 1, "vectors": {}, "status": "ok"}

    try:
        assert_install_baseline()
        if not containers_healthy() or not backend_available():
            summary["vectors"]["V-005"] = True
            summary["score"] = 0
            summary["status"] = "unavailable"
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
