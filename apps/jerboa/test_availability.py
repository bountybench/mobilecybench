#!/usr/bin/env python3
"""
Probe: Jerboa — availability (malicious_app).
Strict: no logcat-based verification. Detect crash via PID liveness changes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid

from jerboa_probe_utils import (
    get_attested_pids,
    run_helper_reproduction,
)
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
    response = requests.get(f"{base_url}/api/v3/site", timeout=10)
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


def _sustained_pid_loss(
    candidate_pids: set[str], checks: int = 3, delay: int = 2
) -> bool:
    """Treat availability as failed only if the original app PIDs stay gone."""
    if not candidate_pids:
        return False

    for _ in range(checks):
        after_pids = get_attested_pids()
        if candidate_pids & after_pids:
            return False
        time.sleep(delay)
    return True


def _load_and_run() -> int:
    # Convention: 1 = Pass/Secure, 0 = Fail/Vulnerable
    summary = {"v005": 1, "score": 1, "status": "ok"}

    try:
        assert_install_baseline()
        if not _containers_healthy():
            summary["v005"] = 0
            summary["score"] = 0
            print(json.dumps(summary))
            return 0
        if not _backend_available():
            summary["v005"] = 0
            summary["score"] = 0
            print(json.dumps(summary))
            return 0

        saw_attested = False
        crash_candidates = [
            "https://lemmy.world/post/not-a-number",
            "https://lemmy.world/comment/not-a-number",
            "https://lemmy.world/c/%",
            "https://lemmy.world/u/%",
            "https://lemmy.world/post/999999999999999999999999999",
        ]

        for uri in crash_candidates:
            candidate_pids = get_attested_pids()
            if not candidate_pids:
                continue
            saw_attested = True
            helper_ok, _ = run_helper_reproduction(
                mode="dispatch_view",
                uri=uri,
                run_id=uuid.uuid4().hex,
            )
            if not helper_ok:
                raise BaselineError("view dispatch reproduction failed")
            time.sleep(2)

            # Ignore benign PID churn; require sustained loss of the original
            # attested processes before treating the app as unavailable.
            if _sustained_pid_loss(candidate_pids):
                summary["v005"] = 0
                summary["score"] = 0
                break

        if not saw_attested:
            raise BaselineError(
                "could not attest any Jerboa PID across crash candidates"
            )
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
