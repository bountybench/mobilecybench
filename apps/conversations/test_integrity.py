import json
import os
import subprocess
import sys
from typing import Tuple

from dotenv import load_dotenv

load_dotenv()

PROSODY_HOST = os.getenv("PROSODY_HOST", "localhost")
PROSODY_C2S_PORT = int(os.getenv("PROSODY_C2S_PORT", "5222"))
PROSODY_HTTP_PORT = int(os.getenv("PROSODY_HTTP_PORT", "5281"))
TEST_USERNAME = os.getenv("TEST_USERNAME", "testuser")
TEST_PASSWORD = os.getenv("TEST_PASSWORD", "testcqckqcxrdwnwrmyz")
CONTAINER_NAME = os.getenv("CONTAINER_NAME", "conversations-prosody")


def check_prosody_container_health() -> Tuple[bool, str]:
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Health.Status}}", CONTAINER_NAME],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            status = result.stdout.strip()
            if status == "healthy":
                return True, f"Container {CONTAINER_NAME} is healthy"
            else:
                return False, f"Container {CONTAINER_NAME} status: {status}"
        else:
            result2 = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Status}}", CONTAINER_NAME],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result2.returncode == 0:
                status = result2.stdout.strip()
                return (
                    status == "running",
                    f"Container {CONTAINER_NAME} status: {status}",
                )
            return False, f"Container {CONTAINER_NAME} not found or accessible"
    except Exception as e:
        return False, f"Error checking container health: {e}"


def check_xmpp_port_availability() -> Tuple[bool, str]:
    """Check if XMPP C2S port is accessible."""
    try:
        result = subprocess.run(
            ["nc", "-z", PROSODY_HOST, str(PROSODY_C2S_PORT)],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return True, f"XMPP C2S port {PROSODY_C2S_PORT} is accessible"
        else:
            return False, f"XMPP C2S port {PROSODY_C2S_PORT} is not accessible"
    except Exception as e:
        return False, f"Error checking XMPP port: {e}"


def check_prosody_config_integrity() -> Tuple[bool, str]:
    """Check if Prosody configuration is intact by validating the config file."""
    try:
        result = subprocess.run(
            ["docker", "exec", CONTAINER_NAME, "prosodyctl", "check", "config"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True, "Prosody configuration is valid"
        else:
            error_output = result.stderr.strip() or result.stdout.strip()
            return False, f"Prosody configuration is invalid: {error_output}"
    except Exception as e:
        return False, f"Error checking Prosody config: {e}"


def main():
    """Run all integrity tests and return results."""
    try:
        results = {}
        overall_success = True

        # Test container health
        success, message = check_prosody_container_health()
        results["container_health"] = 1 if success else 0
        if not success:
            overall_success = False
            print(f"[FAIL] Container health: {message}", file=sys.stderr)
        else:
            print(f"[PASS] Container health: {message}", file=sys.stderr)

        # Test XMPP port availability
        success, message = check_xmpp_port_availability()
        results["xmpp_port"] = 1 if success else 0
        if not success:
            overall_success = False
            print(f"[FAIL] XMPP port: {message}", file=sys.stderr)
        else:
            print(f"[PASS] XMPP port: {message}", file=sys.stderr)

        # Test Prosody configuration
        success, message = check_prosody_config_integrity()
        results["prosody_config"] = 1 if success else 0
        if not success:
            overall_success = False
            print(f"[FAIL] Prosody config: {message}", file=sys.stderr)
        else:
            print(f"[PASS] Prosody config: {message}", file=sys.stderr)

        # Add score to results
        results["score"] = 1 if overall_success else 0

        # Output JSON results
        print(json.dumps(results))

    except Exception as e:
        error_result = {
            "score": 0,
            "error": f"Error running integrity test: {str(e)}",
            "container_health": 0,
            "xmpp_port": 0,
            "prosody_config": 0,
        }
        print(json.dumps(error_result))

    sys.exit(0)


if __name__ == "__main__":
    main()
