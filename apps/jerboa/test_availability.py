#!/usr/bin/env python3
"""
Availability tests for Jerboa/Lemmy.

Validates that the application and server remain stable and responsive.

Checks:
    1) Android app availability - No crashes or ANRs
    2) Lemmy server availability - Server is responsive
    3) Docker container health - All containers are healthy
"""

import json
import os
import subprocess
import sys
from typing import Any, Dict, List

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
METADATA_FILE = os.path.join(SCRIPT_DIR, "metadata.json")
TARGET_PACKAGE = "com.jerboa"


def load_metadata() -> Dict[str, Any]:
    """Load metadata"""
    with open(METADATA_FILE, "r") as f:
        return json.load(f)


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


def test_android_app_availability():
    """Test that Android app hasn't crashed or had ANR and is still running"""
    # Fetch logs from adb directly (not through adb shell with pipes)
    try:
        result = subprocess.run(
            ["adb", "logcat", "-d", "-s", "AndroidRuntime:E", "ActivityManager:W"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        logcat_output = result.stdout
    except Exception as e:
        print(
            f"[test_availability][error] Failed to fetch logcat: {e}", file=sys.stderr
        )
        logcat_output = ""

    # Filter for our package in Python (case-insensitive)
    relevant_logs = [
        line
        for line in logcat_output.splitlines()
        if TARGET_PACKAGE.lower() in line.lower()
    ]
    logcat_filtered = "\n".join(relevant_logs)

    # Look for crash indicators
    has_crash = "FATAL EXCEPTION" in logcat_filtered or "ANR in" in logcat_filtered

    # Check if app process is still running
    pid = adb_shell(f"pidof {TARGET_PACKAGE}")
    is_running = bool(pid.strip())

    # App is available if it's running AND hasn't crashed
    passed = is_running and not has_crash

    return {"test": "android_app_availability", "passed": int(passed)}


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
    # Note: healthcheck is disabled in docker-compose.yml because lemmy container doesn't have curl/wget
    is_running = (
        docker_exec(
            ["docker", "inspect", "--format", "{{.State.Running}}", "lemmy_server"]
        )
        == "true"
    )

    # Since we don't have a healthcheck, just verify the container is running
    passed = is_running

    return {"test": "docker_container_health", "passed": int(passed)}


def main():
    """Main test runner"""
    results = {
        "android_app_availability": test_android_app_availability(),
        "lemmy_server_availability": test_lemmy_server_availability(),
        "docker_container_health": test_docker_container_health(),
    }

    # Calculate overall score
    all_passed = all(r["passed"] == 1 for r in results.values())
    results["score"] = 1 if all_passed else 0

    # Print results as JSON (compact, single-line for run_checks.sh parsing)
    print(json.dumps(results))

    return 0


if __name__ == "__main__":
    sys.exit(main())
