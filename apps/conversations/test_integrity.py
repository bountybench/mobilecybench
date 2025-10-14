import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Tuple

# Load secrets
script_dir = Path(__file__).parent
with open(script_dir / "secrets.json") as f:
    secrets = json.load(f)

PROSODY_HOST = os.getenv("PROSODY_HOST", "localhost")
PROSODY_C2S_PORT = "5222"
PROSODY_HTTP_PORT = "5281"
TEST_USERNAME = "testuser"
TEST_PASSWORD = secrets["testuser_password"]
CONTAINER_NAME = "conversations-prosody"


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
            "prosody_config": 0,
        }
        print(json.dumps(error_result))

    sys.exit(0)


if __name__ == "__main__":
    main()
