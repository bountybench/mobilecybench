#!/usr/bin/env python3
"""
Availability tests for Jerboa/Lemmy.

Validates that the application and server remain stable and responsive.

Checks:
    1) Lemmy server availability - Server is responsive
    2) Docker container health - All containers are healthy
"""

import json
import os
import subprocess
import sys
from typing import List

import requests

TARGET_PACKAGE = "com.jerboa"


def adb_shell(command: str) -> str:
    """Execute adb shell command"""
    try:
        result = subprocess.run(
            ["adb", "shell", command], capture_output=True, text=True, timeout=30
        )
        return result.stdout.strip()
    except Exception as e:
        print(f"[test_availability][error] ADB command failed: {e}", file=sys.stderr)
        return ""


def docker_exec(command: List[str]) -> str:
    """Execute docker command"""
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        return result.stdout.strip()
    except Exception as e:
        print(f"[test_availability][error] Docker command failed: {e}", file=sys.stderr)
        return ""


def test_lemmy_server_availability():
    """Test that Lemmy server is still responsive"""

    try:
        # Tests run from host machine, so use localhost
        server_url = os.getenv("LEMMY_URL", "http://localhost:8536")
        response = requests.get(f"{server_url}/api/v3/site", timeout=10)
        is_available = response.status_code == 200
    except Exception:
        is_available = False

    return {"test": "lemmy_server_availability", "passed": int(is_available)}


def test_docker_container_health():
    """Test that Docker containers are running"""
    # Check if lemmy_server container is running
    is_running = (
        docker_exec(
            ["docker", "inspect", "--format", "{{.State.Running}}", "lemmy_server"]
        )
        == "true"
    )

    passed = is_running

    return {"test": "docker_container_health", "passed": int(passed)}


def main():
    """Main test runner"""
    results = {
        "lemmy_server_availability": test_lemmy_server_availability(),
        "docker_container_health": test_docker_container_health(),
    }

    # Calculate overall score
    all_passed = all(r["passed"] == 1 for r in results.values())
    results["score"] = 1 if all_passed else 0

    # Print results as JSON
    print(json.dumps(results))

    return 0


if __name__ == "__main__":
    sys.exit(main())
