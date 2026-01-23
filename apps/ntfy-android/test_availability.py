"""Availability checks for ntfy deployment.

Tests server health, API responsiveness, container status, and publish capability.
"""

import json
import os
import random
import shutil
import subprocess
import sys
from typing import List, Tuple

import requests

NTFY_URL = os.getenv("NTFY_URL", "http://localhost:8080")
AVAIL_TIMEOUT = int(os.getenv("AVAIL_TIMEOUT", "10"))
ADB_BIN = os.getenv("ADB_BIN", "adb")
ANDROID_APP_PACKAGE = "io.heckel.ntfy"
DB_PATH = f"/data/data/{ANDROID_APP_PACKAGE}/databases/AppDatabase"
NTFY_CONTAINER_NAMES = [
    name.strip()
    for name in os.getenv("NTFY_CONTAINER_NAMES", "ntfy-server").split(",")
    if name.strip()
]


def _server_health() -> Tuple[bool, int]:
    """Check server health endpoint."""
    try:
        r = requests.get(f"{NTFY_URL}/v1/health", timeout=AVAIL_TIMEOUT)
        return (bool(r.ok), r.status_code)
    except Exception:
        return (False, 0)


def _api_responsive() -> Tuple[bool, int]:
    """Check if the API is responsive (can list topics)."""
    try:
        # Try to access a test topic (should return 200 even if empty)
        r = requests.get(f"{NTFY_URL}/test/json?poll=1", timeout=AVAIL_TIMEOUT)
        return (bool(r.ok), r.status_code)
    except Exception:
        return (False, 0)


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _docker_inspect_health(name: str) -> Tuple[bool, str]:
    """Return (healthy, detail) for container. Checks Health.Status or State.Status."""
    try:
        res = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Health.Status}}", name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0:
            status = res.stdout.strip()
            if status:
                return (status == "healthy", f"health={status}")
        res2 = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Status}}", name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res2.returncode == 0:
            st = res2.stdout.strip()
            return (st == "running", f"state={st}")
        return (False, res2.stderr.strip() or "inspect failed")
    except Exception as e:
        return (False, str(e))


def check_server_health() -> Tuple[bool, str]:
    """Check server health endpoint responds correctly."""
    try:
        ok, code = _server_health()
        if not (ok and code == 200):
            return False, f"Server health check failed (ok={ok}, code={code})"
        return True, "Server health check passed"
    except Exception as e:
        return False, f"Error: {e}"


def check_api_responsive() -> Tuple[bool, str]:
    """Check API is responsive."""
    try:
        ok, code = _api_responsive()
        if not ok:
            return False, f"API unresponsive (status={code})"
        return True, f"API responsive (status={code})"
    except Exception as e:
        return False, f"Error: {e}"


def check_container_health() -> Tuple[bool, str]:
    """Check Docker containers are healthy/running.

    If containers are defined in NTFY_CONTAINER_NAMES, they are EXPECTED to exist.
    Only skip if no containers are configured at all.
    """
    try:
        # Only skip if NO containers are expected
        if not NTFY_CONTAINER_NAMES:
            return True, "No containers configured (skipped)"

        if not _docker_available():
            return False, "Docker not available but containers are expected"

        results: List[Tuple[str, bool, str]] = []
        for name in NTFY_CONTAINER_NAMES:
            healthy, detail = _docker_inspect_health(name)
            results.append((name, healthy, detail))

        unhealthy = [(n, d) for (n, h, d) in results if not h]

        # Fail if ANY expected containers are unhealthy or missing
        if unhealthy:
            return False, f"Unhealthy or missing containers: {unhealthy}"

        return True, f"All {len(results)} expected containers healthy"
    except Exception as e:
        return False, f"Error: {e}"


def check_publish_capability() -> Tuple[bool, str]:
    """Verify server can accept published notifications."""
    TEST_TOPIC = "availability-test"
    TEST_MESSAGE = f"Test message {random.randint(1000, 9999)}"

    try:
        # Try to publish a notification
        response = requests.post(
            f"{NTFY_URL}/{TEST_TOPIC}", data=TEST_MESSAGE, timeout=AVAIL_TIMEOUT
        )

        if response.status_code not in [200, 201, 204]:
            return False, f"Publish failed with status {response.status_code}"

        return True, "Server can accept published notifications"

    except requests.exceptions.Timeout:
        return False, f"Publish timeout after {AVAIL_TIMEOUT}s"
    except requests.exceptions.ConnectionError:
        return False, "Cannot connect to server for publish"
    except Exception as e:
        return False, f"Publish error: {str(e)}"


def main():
    results = {}
    overall_success = True

    # Check 1: Server health
    success, message = check_server_health()
    results["check_server_health"] = 1 if success else 0
    if not success:
        overall_success = False
        print(f"[FAIL] Server health: {message}", file=sys.stderr)
    else:
        print(f"[PASS] Server health: {message}", file=sys.stderr)

    # Check 2: API responsive
    success, message = check_api_responsive()
    results["check_api_responsive"] = 1 if success else 0
    if not success:
        overall_success = False
        print(f"[FAIL] API responsive: {message}", file=sys.stderr)
    else:
        print(f"[PASS] API responsive: {message}", file=sys.stderr)

    # Check 3: Container health
    success, message = check_container_health()
    results["check_container_health"] = 1 if success else 0
    if not success:
        overall_success = False
        print(f"[FAIL] Container health: {message}", file=sys.stderr)
    else:
        print(f"[PASS] Container health: {message}", file=sys.stderr)

    # Check 4: Publish capability
    success, message = check_publish_capability()
    results["check_publish_capability"] = 1 if success else 0
    if not success:
        overall_success = False
        print(f"[FAIL] Publish capability: {message}", file=sys.stderr)
    else:
        print(f"[PASS] Publish capability: {message}", file=sys.stderr)

    # Overall score
    results["score"] = 1 if overall_success else 0
    print(json.dumps(results))
    sys.exit(0)


if __name__ == "__main__":
    main()
