"""Availability tests for Jellyfin media server app.

This module verifies service availability and runtime stability for the Jellyfin Android client:

1) Backend service health
   - Jellyfin server is running and responsive
   - Container health checks pass
   - Network connectivity is maintained

2) Jellyfin service responsiveness
   - HTTP web interface responds to connections
   - API endpoints are accessible
   - Health check endpoint is functional

3) Android app runtime stability
   - Uses adb logcat to detect fatal crashes related to Jellyfin app
   - Monitors for Application Not Responding (ANR) events
   - Checks for service disconnections or connection failures

Environment variables:
  JELLYFIN_HOST        : Jellyfin server hostname (default: localhost)
  JELLYFIN_PORT        : Jellyfin server port (default: 8096)
  JELLYFIN_HTTPS_PORT  : HTTPS server port (default: 8920)
  AVAIL_TIMEOUT        : HTTP timeout in seconds (default: 5)
  ADB_BIN              : Path to adb binary (default: adb)
  CONTAINER_NAME       : Jellyfin container name (default: jellyfin-server)
"""

import os
import shutil
import subprocess
import sys
from typing import List, Tuple

import pytest
import requests
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
from utils.availability_utils import check_DOS

load_dotenv()

JELLYFIN_HOST = os.getenv("JELLYFIN_HOST", "localhost")
JELLYFIN_PORT = int(os.getenv("JELLYFIN_PORT", "8096"))
JELLYFIN_HTTPS_PORT = int(os.getenv("JELLYFIN_HTTPS_PORT", "8920"))
AVAIL_TIMEOUT = int(os.getenv("AVAIL_TIMEOUT", "5"))
ADB_BIN = os.getenv("ADB_BIN", "adb")
CONTAINER_NAME = os.getenv("CONTAINER_NAME", "jellyfin-server")
ANDROID_APP_PACKAGE = "org.jellyfin.mobile"

JELLYFIN_BASE_URL = f"http://{JELLYFIN_HOST}:{JELLYFIN_PORT}"


# --- Helpers ---


def _jellyfin_http_probe() -> int:
    """Probe Jellyfin HTTP port connectivity.

    Returns 1 for successful connection, 0 for connection failure.
    """
    try:
        result = subprocess.run(
            ["nc", "-z", "-w", "3", JELLYFIN_HOST, str(JELLYFIN_PORT)],
            capture_output=True,
            timeout=AVAIL_TIMEOUT,
        )
        return 1 if result.returncode == 0 else 0
    except Exception:
        return 0


def _jellyfin_https_probe() -> int:
    """Probe Jellyfin HTTPS port connectivity.

    Returns 1 for successful connection, 0 for connection failure.
    """
    try:
        result = subprocess.run(
            ["nc", "-z", "-w", "3", JELLYFIN_HOST, str(JELLYFIN_HTTPS_PORT)],
            capture_output=True,
            timeout=AVAIL_TIMEOUT,
        )
        return 1 if result.returncode == 0 else 0
    except Exception:
        return 0


def _jellyfin_health_check() -> int:
    """Check Jellyfin health endpoint.

    Returns 1 for healthy, 0 for unhealthy or unreachable.
    """
    try:
        health_url = f"{JELLYFIN_BASE_URL}/health"
        response = requests.get(health_url, timeout=AVAIL_TIMEOUT)
        return 1 if response.status_code == 200 else 0
    except Exception:
        return 0


def _jellyfin_api_probe() -> int:
    """Probe Jellyfin API availability.

    Returns 1 for accessible, 0 for inaccessible.
    """
    try:
        api_url = f"{JELLYFIN_BASE_URL}/System/Info/Public"
        response = requests.get(api_url, timeout=AVAIL_TIMEOUT)
        return 1 if response.status_code == 200 else 0
    except Exception:
        return 0


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _docker_container_running(name: str) -> Tuple[bool, str]:
    """Check if container is running and healthy."""
    try:
        # Check health status first
        res = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Health.Status}}", name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0:
            status = res.stdout.strip()
            if status == "healthy":
                return (True, f"healthy")
            elif status:
                return (False, f"health={status}")

        # Fallback to checking running status
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


def _adb_available() -> bool:
    path = shutil.which(ADB_BIN)
    return path is not None


def _adb_has_device() -> bool:
    try:
        res = subprocess.run(
            [ADB_BIN, "devices"], capture_output=True, text=True, timeout=5
        )
        if res.returncode != 0:
            return False
        # Lines with '\tdevice' indicate connected devices
        for line in res.stdout.splitlines()[1:]:  # skip header
            if line.strip().endswith("\tdevice"):
                return True
        return False
    except Exception:
        return False


# --- Tests ---


def test_jellyfin_http_port_accessible():
    """Jellyfin HTTP port should be accessible."""
    result = _jellyfin_http_probe()
    assert result == 1, f"Jellyfin HTTP port {JELLYFIN_PORT} not accessible"


def test_jellyfin_https_port_accessible():
    """Jellyfin HTTPS port should be accessible."""
    result = _jellyfin_https_probe()
    assert result == 1, f"Jellyfin HTTPS port {JELLYFIN_HTTPS_PORT} not accessible"


def test_jellyfin_health_endpoint():
    """Jellyfin health endpoint should return healthy status."""
    result = _jellyfin_health_check()
    assert result == 1, f"Jellyfin health endpoint not responding properly"


def test_jellyfin_api_accessible():
    """Jellyfin API should be accessible."""
    result = _jellyfin_api_probe()
    assert result == 1, f"Jellyfin API not accessible"


def test_jellyfin_container_running_when_docker_present():
    """Jellyfin container should be running when Docker is available."""
    if not _docker_available():
        pytest.skip("Docker not available")

    running, detail = _docker_container_running(CONTAINER_NAME)

    if "No such object" in detail:
        pytest.skip("Jellyfin container not found in this environment")

    assert running, f"Jellyfin container not running: {detail}"


def test_android_app_no_fatal_crashes_via_adb():
    """Jellyfin Android app should not have fatal crashes or ANR events.

    - Skip if adb not available or device missing
    - Use availability_utils.check_DOS to scan for app-related crashes
    """
    if not _adb_available() or not _adb_has_device():
        pytest.skip("adb not available or no device connected")

    pkg = ANDROID_APP_PACKAGE
    try:
        ok = check_DOS(pkg)
    except Exception as e:
        pytest.skip(f"Unable to read adb logs: {e}")

    assert ok, f"Detected crash or ANR for {pkg} via availability_utils.check_DOS"


def main():
    """Run all availability tests and return JSON results."""
    import json
    import sys

    results = {}
    overall_success = True

    # Test Jellyfin HTTP port
    try:
        result = _jellyfin_http_probe()
        success = result == 1
        results["jellyfin_http_port_accessible"] = success
        if not success:
            overall_success = False
            print(
                f"[FAIL] Jellyfin HTTP port: Port {JELLYFIN_PORT} not accessible",
                file=sys.stderr,
            )
        else:
            print(
                f"[PASS] Jellyfin HTTP port: Port {JELLYFIN_PORT} accessible",
                file=sys.stderr,
            )
    except Exception as e:
        overall_success = False
        results["jellyfin_http_port_accessible"] = False
        print(f"[FAIL] Jellyfin HTTP port: {e}", file=sys.stderr)

    # Test Jellyfin HTTPS port
    try:
        result = _jellyfin_https_probe()
        success = result == 1
        results["jellyfin_https_port_accessible"] = success
        if not success:
            overall_success = False
            print(
                f"[FAIL] Jellyfin HTTPS port: Port {JELLYFIN_HTTPS_PORT} not accessible",
                file=sys.stderr,
            )
        else:
            print(
                f"[PASS] Jellyfin HTTPS port: Port {JELLYFIN_HTTPS_PORT} accessible",
                file=sys.stderr,
            )
    except Exception as e:
        overall_success = False
        results["jellyfin_https_port_accessible"] = False
        print(f"[FAIL] Jellyfin HTTPS port: {e}", file=sys.stderr)

    # Test Jellyfin health endpoint
    try:
        result = _jellyfin_health_check()
        success = result == 1
        results["jellyfin_health_endpoint"] = success
        if not success:
            overall_success = False
            print(f"[FAIL] Jellyfin health: Health endpoint not responding", file=sys.stderr)
        else:
            print(f"[PASS] Jellyfin health: Health endpoint responding", file=sys.stderr)
    except Exception as e:
        overall_success = False
        results["jellyfin_health_endpoint"] = False
        print(f"[FAIL] Jellyfin health: {e}", file=sys.stderr)

    # Test Jellyfin API
    try:
        result = _jellyfin_api_probe()
        success = result == 1
        results["jellyfin_api_accessible"] = success
        if not success:
            overall_success = False
            print(f"[FAIL] Jellyfin API: API not accessible", file=sys.stderr)
        else:
            print(f"[PASS] Jellyfin API: API accessible", file=sys.stderr)
    except Exception as e:
        overall_success = False
        results["jellyfin_api_accessible"] = False
        print(f"[FAIL] Jellyfin API: {e}", file=sys.stderr)

    # Test container running
    try:
        if _docker_available():
            running, detail = _docker_container_running(CONTAINER_NAME)
            results["jellyfin_container_running"] = running
            if not running:
                overall_success = False
                print(f"[FAIL] Container running: {detail}", file=sys.stderr)
            else:
                print(f"[PASS] Container running: {detail}", file=sys.stderr)
        else:
            results["jellyfin_container_running"] = True  # Skip if no docker
            print(f"[SKIP] Container running: Docker not available", file=sys.stderr)
    except Exception as e:
        overall_success = False
        results["jellyfin_container_running"] = False
        print(f"[FAIL] Container running: {e}", file=sys.stderr)

    # Test Android app crashes
    try:
        if _adb_available() and _adb_has_device():
            from utils.availability_utils import check_DOS

            ok = check_DOS(ANDROID_APP_PACKAGE)
            results["android_app_no_crashes"] = ok
            if not ok:
                overall_success = False
                print(
                    f"[FAIL] Android app: Detected crashes for {ANDROID_APP_PACKAGE}",
                    file=sys.stderr,
                )
            else:
                print(
                    f"[PASS] Android app: No crashes detected for {ANDROID_APP_PACKAGE}",
                    file=sys.stderr,
                )
        else:
            results["android_app_no_crashes"] = True  # Skip if no adb/device
            print(
                f"[SKIP] Android app: adb not available or no device", file=sys.stderr
            )
    except Exception as e:
        overall_success = False
        results["android_app_no_crashes"] = False
        print(f"[FAIL] Android app: {e}", file=sys.stderr)

    # Output JSON results
    print(json.dumps(results))

    if overall_success:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()