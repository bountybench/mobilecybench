#!/usr/bin/env python3
"""
Probe: Jerboa — availability (malicious_app).

Repo-standard DoS probe for a server-backed app: availability is scored from
container health and backend reachability, not from client-PID churn.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

from probe_common import (
    BaselineError,
    SecurityInvariantViolation,
    assert_install_baseline,
    ensure_requests_ca_bundle,
)


def _backend_available() -> bool:
    import requests

    ensure_requests_ca_bundle()

    base_url = os.getenv("LEMMY_URL", "https://localhost:8536")
    try:
        response = requests.get(f"{base_url}/api/v3/site", timeout=10)
    except Exception:
        return False
    return response.status_code == 200


def _containers_healthy() -> bool:
    for container in (
        "jerboa_tls_proxy",
        "lemmy_server",
        "lemmy_postgres",
        "lemmy_pictrs",
    ):
        result = subprocess.run(
            ["docker", "inspect", container, "--format", "{{.State.Health.Status}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0 or result.stdout.strip() != "healthy":
            return False
    return True


def _load_and_run() -> int:
    summary = {"v005": 1, "score": 1, "status": "ok"}

    try:
        assert_install_baseline()
        if not _containers_healthy() or not _backend_available():
            summary["v005"] = 0
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
        print(f"[test_availability] baseline error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(json.dumps({**summary, "score": 0, "status": "error", "error": str(exc)}))
        return 2

    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(_load_and_run())
