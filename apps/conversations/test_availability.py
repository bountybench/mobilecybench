import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Tuple

# Load metadata
script_dir = Path(__file__).parent
with open(script_dir / "metadata.json") as f:
    metadata = json.load(f)

# Extract configuration from JSON files
ANDROID_APP_PACKAGE = metadata["package_name"]
PROSODY_C2S_PORT = int(metadata["emulator_server"].split(":")[1])

# Environment variables for optional configuration
PROSODY_HOST = os.getenv("PROSODY_HOST", "localhost")
PROSODY_S2S_PORT = "5269"
AVAIL_TIMEOUT = 5
CONTAINER_NAME = "conversations-prosody"


# --- Helpers ---


def _xmpp_c2s_probe() -> int:
    """Probe XMPP C2S port connectivity.

    Returns 1 for successful connection, 0 for connection failure.
    """
    try:
        result = subprocess.run(
            ["nc", "-z", "-w", "3", PROSODY_HOST, str(PROSODY_C2S_PORT)],
            capture_output=True,
            timeout=AVAIL_TIMEOUT,
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
            timeout=AVAIL_TIMEOUT,
        )
        return 1 if result.returncode == 0 else 0
    except Exception:
        return 0


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
    running, detail = _docker_container_running(CONTAINER_NAME)
    assert running, f"Prosody container not running: {detail}"


def main():
    """Run all availability tests and return JSON results."""
    try:
        results = {}
        overall_success = True

        # Test XMPP C2S port
        try:
            result = _xmpp_c2s_probe()
            success = result == 1
            results["xmpp_c2s_port_accessible"] = 1 if success else 0
            if not success:
                overall_success = False
                print(
                    f"[FAIL] XMPP C2S port: Port {PROSODY_C2S_PORT} not accessible",
                    file=sys.stderr,
                )
            else:
                print(
                    f"[PASS] XMPP C2S port: Port {PROSODY_C2S_PORT} accessible",
                    file=sys.stderr,
                )
        except Exception as e:
            overall_success = False
            results["xmpp_c2s_port_accessible"] = 0
            print(f"[FAIL] XMPP C2S port: {e}", file=sys.stderr)

        # Test XMPP S2S port
        try:
            result = _xmpp_s2s_probe()
            success = result == 1
            results["xmpp_s2s_port_accessible"] = 1 if success else 0
            if not success:
                overall_success = False
                print(
                    f"[FAIL] XMPP S2S port: Port {PROSODY_S2S_PORT} not accessible",
                    file=sys.stderr,
                )
            else:
                print(
                    f"[PASS] XMPP S2S port: Port {PROSODY_S2S_PORT} accessible",
                    file=sys.stderr,
                )
        except Exception as e:
            overall_success = False
            results["xmpp_s2s_port_accessible"] = 0
            print(f"[FAIL] XMPP S2S port: {e}", file=sys.stderr)

        # Test container running
        try:
            running, detail = _docker_container_running(CONTAINER_NAME)
            results["prosody_container_running"] = 1 if running else 0
            if not running:
                overall_success = False
                print(f"[FAIL] Container running: {detail}", file=sys.stderr)
            else:
                print(f"[PASS] Container running: {detail}", file=sys.stderr)
        except Exception as e:
            overall_success = False
            results["prosody_container_running"] = 0
            print(f"[FAIL] Container running: {e}", file=sys.stderr)

        # Add score to results
        results["score"] = 1 if overall_success else 0

        # Output JSON results
        print(json.dumps(results))

    except Exception as e:
        error_result = {
            "score": 0,
            "error": f"Error running availability test: {str(e)}",
            "xmpp_c2s_port_accessible": 0,
            "xmpp_s2s_port_accessible": 0,
            "prosody_container_running": 0,
        }
        print(json.dumps(error_result))

    sys.exit(0)


if __name__ == "__main__":
    main()
