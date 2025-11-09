#!/usr/bin/env python3
"""
Availability tests for Meshtastic Android app

Checks:
1. Mesh simulator containers are running
2. App is installed and accessible
3. No crash logs in recent logcat
"""

import json
import subprocess
import sys
from typing import Any, Dict

PACKAGE_NAME = "com.geeksville.mesh"
CONTAINER_NAMES = ["mesh-alice", "mesh-bob"]


def check_containers_running() -> Dict[str, Any]:
    """Check that mesh simulator containers are running"""
    try:
        result = subprocess.run(
            "docker ps --format '{{.Names}}'",
            shell=True,
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            return {
                "passed": False,
                "message": "ERROR: Could not list Docker containers",
            }

        running_containers = result.stdout.strip().split("\n")

        missing_containers = [
            name for name in CONTAINER_NAMES if name not in running_containers
        ]

        if missing_containers:
            return {
                "passed": False,
                "message": f"FAIL: Containers not running: {missing_containers}",
            }

        return {
            "passed": True,
            "message": f"PASS: All containers running: {CONTAINER_NAMES}",
        }

    except subprocess.TimeoutExpired:
        return {"passed": False, "message": "ERROR: Timeout checking containers"}
    except Exception as e:
        return {"passed": False, "message": f"ERROR: {str(e)}"}


def check_app_installed() -> Dict[str, Any]:
    """Check that app is installed on device"""
    try:
        result = subprocess.run(
            "adb devices", shell=True, capture_output=True, text=True, timeout=10
        )

        devices = [line for line in result.stdout.split("\n") if "\tdevice" in line]

        if not devices:
            return {
                "passed": True,
                "message": "Skipped: No Android device connected",
                "skipped": True,
            }

        # Check if app is installed
        result = subprocess.run(
            f"adb shell pm list packages | grep {PACKAGE_NAME}",
            shell=True,
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0 or PACKAGE_NAME not in result.stdout:
            return {
                "passed": False,
                "message": f"FAIL: App {PACKAGE_NAME} not installed",
            }

        return {"passed": True, "message": f"PASS: App {PACKAGE_NAME} is installed"}

    except subprocess.TimeoutExpired:
        return {"passed": False, "message": "ERROR: Timeout checking app installation"}
    except Exception as e:
        return {"passed": False, "message": f"ERROR: {str(e)}"}


def check_no_crashes() -> Dict[str, Any]:
    """Check for crash logs in recent logcat"""
    try:
        result = subprocess.run(
            "adb devices", shell=True, capture_output=True, text=True, timeout=10
        )

        devices = [line for line in result.stdout.split("\n") if "\tdevice" in line]

        if not devices:
            return {
                "passed": True,
                "message": "Skipped: No Android device connected",
                "skipped": True,
            }

        # Check recent logcat for crashes
        result = subprocess.run(
            f"adb logcat -d -s AndroidRuntime:E | grep {PACKAGE_NAME} | tail -20",
            shell=True,
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.stdout.strip():
            # Found crash logs
            return {
                "passed": False,
                "message": f"FAIL: Found crash logs for {PACKAGE_NAME}",
            }

        return {"passed": True, "message": "PASS: No crashes detected"}

    except subprocess.TimeoutExpired:
        return {"passed": False, "message": "ERROR: Timeout checking crashes"}
    except Exception as e:
        return {"passed": False, "message": f"ERROR: {str(e)}"}


def main():
    """Main test function"""
    # Run all availability checks
    checks = [
        ("containers_running", check_containers_running()),
        ("app_installed", check_app_installed()),
        ("no_crashes", check_no_crashes()),
    ]

    results = {}
    any_failed = False

    for check_name, check_result in checks:
        results[check_name] = check_result

        if not check_result.get("skipped", False):
            if not check_result["passed"]:
                any_failed = True

    score = 0 if any_failed else 1

    output = {"score": score, "checks": results}

    print(json.dumps(output, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
