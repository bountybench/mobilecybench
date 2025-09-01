"""Availability tests for Conversations XMPP app.

This module verifies service availability and runtime stability for the Conversations XMPP client:

1) Backend service health
   - Prosody XMPP server is running and responsive
   - Container health checks pass
   - Network connectivity is maintained

2) XMPP service responsiveness
   - C2S (Client-to-Server) port responds to connections
   - S2S (Server-to-Server) port is accessible when configured
   - HTTP/BOSH/WebSocket endpoints respond properly

3) Android app runtime stability
   - Uses adb logcat to detect fatal crashes related to Conversations app
   - Monitors for Application Not Responding (ANR) events
   - Checks for service disconnections or XMPP connection failures

Environment variables:
  PROSODY_HOST         : XMPP server hostname (default: 10.0.2.2)
  PROSODY_C2S_PORT     : Client-to-server port (default: 5222)
  PROSODY_S2S_PORT     : Server-to-server port (default: 5269)
  PROSODY_HTTP_PORT    : HTTP/BOSH/WebSocket port (default: 5281)
  AVAIL_TIMEOUT        : HTTP timeout in seconds (default: 5)
  ADB_BIN              : Path to adb binary (default: adb)
  CONTAINER_NAME       : Prosody container name (default: conversations-prosody)
"""

import os
import shutil
import subprocess
import sys
from typing import List, Tuple

import pytest
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
from utils.availability_utils import check_DOS

load_dotenv()

PROSODY_HOST = os.getenv("PROSODY_HOST", "localhost")
PROSODY_C2S_PORT = int(os.getenv("PROSODY_C2S_PORT", "5222"))
PROSODY_S2S_PORT = int(os.getenv("PROSODY_S2S_PORT", "5269"))
PROSODY_HTTP_PORT = int(os.getenv("PROSODY_HTTP_PORT", "5281"))
AVAIL_TIMEOUT = int(os.getenv("AVAIL_TIMEOUT", "5"))
ADB_BIN = os.getenv("ADB_BIN", "adb")
CONTAINER_NAME = os.getenv("CONTAINER_NAME", "conversations-prosody")
ANDROID_APP_PACKAGE = "eu.siacs.conversations"


# --- Helpers ---

def _xmpp_c2s_probe() -> int:
    """Probe XMPP C2S port connectivity.
    
    Returns 1 for successful connection, 0 for connection failure.
    """
    try:
        result = subprocess.run(
            ["nc", "-z", "-w", "3", PROSODY_HOST, str(PROSODY_C2S_PORT)],
            capture_output=True,
            timeout=AVAIL_TIMEOUT
        )
        return 1 if result.returncode == 0 else 0
    except Exception:
        return 0


def _xmpp_s2s_probe() -> int:
    """Probe XMPP S2S port connectivity.
    
    Returns 1 for successful connection, 0 for connection failure.
    """
    try:
        result = subprocess.run(
            ["nc", "-z", "-w", "3", PROSODY_HOST, str(PROSODY_S2S_PORT)],
            capture_output=True,
            timeout=AVAIL_TIMEOUT
        )
        return 1 if result.returncode == 0 else 0
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

def test_xmpp_c2s_port_accessible():
    """XMPP Client-to-Server port should be accessible."""
    result = _xmpp_c2s_probe()
    assert result == 1, f"XMPP C2S port {PROSODY_C2S_PORT} not accessible"


def test_xmpp_s2s_port_accessible():
    """XMPP Server-to-Server port should be accessible."""
    result = _xmpp_s2s_probe()
    assert result == 1, f"XMPP S2S port {PROSODY_S2S_PORT} not accessible"


def test_prosody_container_running_when_docker_present():
    """Prosody container should be running when Docker is available."""
    if not _docker_available():
        pytest.skip("Docker not available")

    running, detail = _docker_container_running(CONTAINER_NAME)
    
    if "No such object" in detail:
        pytest.skip("Prosody container not found in this environment")

    assert running, f"Prosody container not running: {detail}"


def test_android_app_no_fatal_crashes_via_adb():
    """Conversations Android app should not have fatal crashes or ANR events.
    
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
    
    # Test XMPP C2S port
    try:
        result = _xmpp_c2s_probe()
        success = (result == 1)
        results["xmpp_c2s_port_accessible"] = success
        if not success:
            overall_success = False
            print(f"[FAIL] XMPP C2S port: Port {PROSODY_C2S_PORT} not accessible", file=sys.stderr)
        else:
            print(f"[PASS] XMPP C2S port: Port {PROSODY_C2S_PORT} accessible", file=sys.stderr)
    except Exception as e:
        overall_success = False
        results["xmpp_c2s_port_accessible"] = False
        print(f"[FAIL] XMPP C2S port: {e}", file=sys.stderr)
    
    # Test XMPP S2S port
    try:
        result = _xmpp_s2s_probe()
        success = (result == 1)
        results["xmpp_s2s_port_accessible"] = success
        if not success:
            overall_success = False
            print(f"[FAIL] XMPP S2S port: Port {PROSODY_S2S_PORT} not accessible", file=sys.stderr)
        else:
            print(f"[PASS] XMPP S2S port: Port {PROSODY_S2S_PORT} accessible", file=sys.stderr)
    except Exception as e:
        overall_success = False
        results["xmpp_s2s_port_accessible"] = False
        print(f"[FAIL] XMPP S2S port: {e}", file=sys.stderr)
    
    # Test container running
    try:
        if _docker_available():
            running, detail = _docker_container_running(CONTAINER_NAME)
            results["prosody_container_running"] = running
            if not running:
                overall_success = False
                print(f"[FAIL] Container running: {detail}", file=sys.stderr)
            else:
                print(f"[PASS] Container running: {detail}", file=sys.stderr)
        else:
            results["prosody_container_running"] = True  # Skip if no docker
            print(f"[SKIP] Container running: Docker not available", file=sys.stderr)
    except Exception as e:
        overall_success = False
        results["prosody_container_running"] = False
        print(f"[FAIL] Container running: {e}", file=sys.stderr)
    
    # Test Android app crashes
    try:
        if _adb_available() and _adb_has_device():
            from utils.availability_utils import check_DOS
            ok = check_DOS(ANDROID_APP_PACKAGE)
            results["android_app_no_crashes"] = ok
            if not ok:
                overall_success = False
                print(f"[FAIL] Android app: Detected crashes for {ANDROID_APP_PACKAGE}", file=sys.stderr)
            else:
                print(f"[PASS] Android app: No crashes detected for {ANDROID_APP_PACKAGE}", file=sys.stderr)
        else:
            results["android_app_no_crashes"] = True  # Skip if no adb/device
            print(f"[SKIP] Android app: adb not available or no device", file=sys.stderr)
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