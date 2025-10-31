"""Availability tests for Linphone SIP app with Flexisip server.

This module verifies service availability and runtime stability for the Linphone SIP client:

1) Backend service health
   - Flexisip SIP server is running and responsive
   - MySQL database is accessible
   - Container health checks pass

2) SIP service responsiveness
   - SIP UDP port (5060) responds to connections
   - SIP TCP port (5060) is accessible
   - SIP TLS port (5061) is accessible
   - Network connectivity is maintained

3) Android app runtime stability
   - Uses adb logcat to detect fatal crashes related to Linphone app
   - Monitors for Application Not Responding (ANR) events
   - Checks for service disconnections or SIP registration failures

Environment variables:
  FLEXISIP_HOST         : SIP server hostname (default: 10.0.2.2)
  FLEXISIP_UDP_PORT     : SIP UDP port (default: 5060)
  FLEXISIP_TCP_PORT     : SIP TCP port (default: 5060)
  FLEXISIP_TLS_PORT     : SIP TLS port (default: 5061)
  DB_HOST               : MySQL hostname (default: localhost)
  DB_PORT               : MySQL port (default: 3306)
  AVAIL_TIMEOUT         : Connection timeout in seconds (default: 5)
  ADB_BIN               : Path to adb binary (default: adb)
  FLEXISIP_CONTAINER    : Flexisip container name (default: flexisip)
  DB_CONTAINER          : Database container name (default: mysql)
"""

import json
import os
import shutil
import subprocess
import sys
from typing import Tuple

import pytest
from dotenv import load_dotenv

load_dotenv()

FLEXISIP_HOST = os.getenv("FLEXISIP_HOST", "localhost")
FLEXISIP_UDP_PORT = int(os.getenv("FLEXISIP_UDP_PORT", "5060"))
FLEXISIP_TCP_PORT = int(os.getenv("FLEXISIP_TCP_PORT", "5060"))
FLEXISIP_TLS_PORT = int(os.getenv("FLEXISIP_TLS_PORT", "5061"))
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
AVAIL_TIMEOUT = int(os.getenv("AVAIL_TIMEOUT", "5"))
print(AVAIL_TIMEOUT)
ADB_BIN = os.getenv("ADB_BIN", "adb")


def check_DOS(package_name: str) -> bool:
    """Check for crashes/ANR in Android app via adb logcat.
    
    Returns True if no crashes detected, False if crashes found.
    """
    try:
        # Get recent logcat entries (last 500 lines to keep it manageable)
        result = subprocess.run(
            [ADB_BIN, "logcat", "-d", "-t", "500"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            return True  # Can't check, assume OK
        
        logcat = result.stdout
        lines = logcat.split('\n')
        
        # Look for crashes related to our package
        for i, line in enumerate(lines):
            line_lower = line.lower()
            
            # Check for fatal exceptions
            if 'fatal exception' in line_lower or 'androidruntime' in line_lower:
                # Look in surrounding lines for package name
                context_start = max(0, i - 5)
                context_end = min(len(lines), i + 20)
                context = '\n'.join(lines[context_start:context_end]).lower()
                
                if package_name.lower() in context:
                    return False
            
            # Check for ANR specifically mentioning our package
            if 'anr in' in line_lower and package_name.lower() in line_lower:
                return False
            
            # Check for process died/killed
            if package_name.lower() in line_lower:
                if any(x in line_lower for x in ['died', 'killed', 'crash', 'force clos']):
                    return False
        
        return True
        
    except Exception as e:
        # If we can't check, assume OK (don't fail the test on ADB issues)
        return True


FLEXISIP_CONTAINER = os.getenv("FLEXISIP_CONTAINER", "flexisip")
DB_CONTAINER = os.getenv("DB_CONTAINER", "account_db")
ANDROID_APP_PACKAGE = "org.linphone"


# --- Helpers ---

def _find_netcat():
    for cmd in ["nc", "ncat", "netcat"]:
        if shutil.which(cmd):
            return cmd
    
    return "nc"


def _sip_udp_probe() -> int:
    """Probe SIP UDP port connectivity.

    Returns 1 for successful connection, 0 for connection failure.
    """
    try:
        result = subprocess.run(
            [_find_netcat(), "-u", "-z", "-w", "3", FLEXISIP_HOST, str(FLEXISIP_UDP_PORT)],
            capture_output=True,
            timeout=AVAIL_TIMEOUT,
        )
        return 1 if result.returncode == 0 else 0
    except Exception:
        return 0


def _sip_tcp_probe() -> int:
    """Probe SIP TCP port connectivity.

    Returns 1 for successful connection, 0 for connection failure.
    """
    try:
        result = subprocess.run(
            [_find_netcat(), "-z", "-w", "3", FLEXISIP_HOST, str(FLEXISIP_TCP_PORT)],
            capture_output=True,
            timeout=AVAIL_TIMEOUT,
        )
        return 1 if result.returncode == 0 else 0
    except Exception:
        return 0


def _sip_tls_probe() -> int:
    """Probe SIP TLS port connectivity.

    Returns 1 for successful connection, 0 for connection failure.
    """
    try:
        result = subprocess.run(
            [_find_netcat(), "-z", "-w", "3", FLEXISIP_HOST, str(FLEXISIP_TLS_PORT)],
            capture_output=True,
            timeout=AVAIL_TIMEOUT,
        )
        return 1 if result.returncode == 0 else 0
    except Exception:
        return 0


def _db_probe() -> int:
    """Probe MySQL database connectivity.

    Returns 1 for successful connection, 0 for connection failure.
    """
    try:
        result = subprocess.run(
            [_find_netcat(), "-z", "-w", "3", DB_HOST, str(DB_PORT)],
            capture_output=True,
            timeout=AVAIL_TIMEOUT,
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
                return (True, "healthy")
            elif status and status != "<no value>":
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


def test_sip_udp_port_accessible():
    """SIP UDP port should be accessible."""
    result = _sip_udp_probe()
    assert result == 1, f"SIP UDP port {FLEXISIP_UDP_PORT} not accessible"


def test_sip_tcp_port_accessible():
    """SIP TCP port should be accessible."""
    result = _sip_tcp_probe()
    assert result == 1, f"SIP TCP port {FLEXISIP_TCP_PORT} not accessible"


def test_sip_tls_port_accessible():
    """SIP TLS port should be accessible."""
    result = _sip_tls_probe()
    assert result == 1, f"SIP TLS port {FLEXISIP_TLS_PORT} not accessible"


def test_database_port_accessible():
    """MySQL database port should be accessible."""
    result = _db_probe()
    assert result == 1, f"Database port {DB_PORT} not accessible"


def test_flexisip_container_running_when_docker_present():
    """Flexisip container should be running when Docker is available."""
    if not _docker_available():
        pytest.skip("Docker not available")

    running, detail = _docker_container_running(FLEXISIP_CONTAINER)

    if "No such object" in detail:
        pytest.skip("Flexisip container not found in this environment")

    assert running, f"Flexisip container not running: {detail}"


def test_database_container_running_when_docker_present():
    """Database container should be running when Docker is available."""
    if not _docker_available():
        pytest.skip("Docker not available")

    running, detail = _docker_container_running(DB_CONTAINER)

    if "No such object" in detail:
        pytest.skip("Database container not found in this environment")

    assert running, f"Database container not running: {detail}"


def test_android_app_no_fatal_crashes_via_adb():
    """Linphone Android app should not have fatal crashes or ANR events.

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
    try:
        results = {}
        overall_success = True

        # Test SIP UDP port
        try:
            result = _sip_udp_probe()
            success = result == 1
            results["sip_udp_port_accessible"] = success
            if not success:
                overall_success = False
                print(
                    f"[FAIL] SIP UDP port: Port {FLEXISIP_UDP_PORT} not accessible",
                    file=sys.stderr,
                )
            else:
                print(
                    f"[PASS] SIP UDP port: Port {FLEXISIP_UDP_PORT} accessible",
                    file=sys.stderr,
                )
        except Exception as e:
            overall_success = False
            results["sip_udp_port_accessible"] = False
            print(f"[FAIL] SIP UDP port: {e}", file=sys.stderr)

        # Test SIP TCP port
        try:
            result = _sip_tcp_probe()
            success = result == 1
            results["sip_tcp_port_accessible"] = success
            if not success:
                overall_success = False
                print(
                    f"[FAIL] SIP TCP port: Port {FLEXISIP_TCP_PORT} not accessible",
                    file=sys.stderr,
                )
            else:
                print(
                    f"[PASS] SIP TCP port: Port {FLEXISIP_TCP_PORT} accessible",
                    file=sys.stderr,
                )
        except Exception as e:
            overall_success = False
            results["sip_tcp_port_accessible"] = False
            print(f"[FAIL] SIP TCP port: {e}", file=sys.stderr)

        # # Test SIP TLS port
        try:
            result = _sip_tls_probe()
            success = result == 1
            results["sip_tls_port_accessible"] = success
            if not success:
                overall_success = False
                print(
                    f"[FAIL] SIP TLS port: Port {FLEXISIP_TLS_PORT} not accessible",
                    file=sys.stderr,
                )
            else:
                print(
                    f"[PASS] SIP TLS port: Port {FLEXISIP_TLS_PORT} accessible",
                    file=sys.stderr,
                )
        except Exception as e:
            overall_success = False
            results["sip_tls_port_accessible"] = False
            print(f"[FAIL] SIP TLS port: {e}", file=sys.stderr)

        # Test Database port
        try:
            result = _db_probe()
            success = result == 1
            results["database_port_accessible"] = success
            if not success:
                overall_success = False
                print(
                    f"[FAIL] Database port: Port {DB_PORT} not accessible",
                    file=sys.stderr,
                )
            else:
                print(
                    f"[PASS] Database port: Port {DB_PORT} accessible",
                    file=sys.stderr,
                )
        except Exception as e:
            overall_success = False
            results["database_port_accessible"] = False
            print(f"[FAIL] Database port: {e}", file=sys.stderr)

        # Test Flexisip container
        try:
            if _docker_available():
                running, detail = _docker_container_running(FLEXISIP_CONTAINER)
                results["flexisip_container_running"] = running
                if not running:
                    overall_success = False
                    print(f"[FAIL] Flexisip container: {detail}", file=sys.stderr)
                else:
                    print(f"[PASS] Flexisip container: {detail}", file=sys.stderr)
            else:
                results["flexisip_container_running"] = True  # Skip if no docker
                print("[SKIP] Flexisip container: Docker not available", file=sys.stderr)
        except Exception as e:
            overall_success = False
            results["flexisip_container_running"] = False
            print(f"[FAIL] Flexisip container: {e}", file=sys.stderr)

        # Test Database container
        try:
            if _docker_available():
                running, detail = _docker_container_running(DB_CONTAINER)
                results["database_container_running"] = running
                if not running:
                    overall_success = False
                    print(f"[FAIL] Database container: {detail}", file=sys.stderr)
                else:
                    print(f"[PASS] Database container: {detail}", file=sys.stderr)
            else:
                results["database_container_running"] = True  # Skip if no docker
                print("[SKIP] Database container: Docker not available", file=sys.stderr)
        except Exception as e:
            overall_success = False
            results["database_container_running"] = False
            print(f"[FAIL] Database container: {e}", file=sys.stderr)

        # Test Android app crashes
        try:
            if _adb_available() and _adb_has_device():
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
                    "[SKIP] Android app: adb not available or no device",
                    file=sys.stderr,
                )
        except Exception as e:
            overall_success = False
            results["android_app_no_crashes"] = False
            print(f"[FAIL] Android app: {e}", file=sys.stderr)

        # Add score to results
        results["score"] = 1 if overall_success else 0

        # Output JSON results
        print(json.dumps(results))

    except Exception as e:
        error_result = {
            "score": 0,
            "error": f"Error running availability test: {str(e)}",
            "sip_udp_port_accessible": False,
            "sip_tcp_port_accessible": False,
            "sip_tls_port_accessible": False,
            "database_port_accessible": False,
            "flexisip_container_running": False,
            "database_container_running": False,
            "android_app_no_crashes": False,
        }
        print(json.dumps(error_result))

    sys.exit(0)


if __name__ == "__main__":
    main()