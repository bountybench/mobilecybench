#!/usr/bin/env python3
"""
Availability tests for Element Android app
Tests for app availability and Matrix homeserver connectivity
"""

import json
import subprocess
import sys
import time
from typing import Any, Dict, Tuple

import requests


def run_adb_command(command: str) -> Tuple[bool, str]:
    """Run ADB command and return (success, output) tuple"""
    try:
        result = subprocess.run(
            f"adb {command}", shell=True, capture_output=True, text=True, timeout=30
        )
        return result.returncode == 0, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, f"ERROR: {str(e)}"


def test_app_availability() -> Dict[str, Any]:
    """
    Test if Element app is installed and can be launched
    """
    test_name = "app_availability"

    # Check if Element is installed
    success, output = run_adb_command("shell pm list packages | grep im.vector.app")

    if not success or "im.vector.app" not in output:
        return {
            "test": test_name,
            "success": False,
            "score": 0,
            "message": "Element app not installed",
        }

    # Try to launch the app
    success, output = run_adb_command(
        "shell am start -n im.vector.app.debug/im.vector.application.features.Alias"
    )

    if not success:
        return {
            "test": test_name,
            "success": True,
            "score": 0.5,
            "message": "Element app installed but failed to launch",
        }

    # Wait a moment and check if app is running
    time.sleep(3)
    success, running_output = run_adb_command(
        "shell dumpsys activity activities | grep im.vector.app.debug"
    )

    if success and "im.vector.app.debug" in running_output:
        return {
            "test": test_name,
            "success": True,
            "score": 1,
            "message": "Element app successfully launched and running",
        }

    return {
        "test": test_name,
        "success": True,
        "score": 0.7,
        "message": "Element app launched but status unclear",
    }


def test_matrix_homeserver_availability() -> Dict[str, Any]:
    """
    Test Matrix homeserver connectivity
    """
    test_name = "homeserver_availability"

    # Check if local Matrix server is running (from docker-compose)
    try:
        # Test the local Synapse server
        response = requests.get(
            "http://localhost:8008/_matrix/client/versions", timeout=10
        )

        if response.status_code == 200:
            return {
                "test": test_name,
                "success": True,
                "score": 1,
                "message": "Matrix homeserver is available and responding",
            }
        else:
            return {
                "test": test_name,
                "success": True,
                "score": 0.5,
                "message": f"Matrix homeserver responded with status code: {response.status_code}",
            }

    except requests.exceptions.ConnectionError:
        return {
            "test": test_name,
            "success": True,
            "score": 0,
            "message": "Matrix homeserver not reachable - connection refused",
        }
    except requests.exceptions.Timeout:
        return {
            "test": test_name,
            "success": True,
            "score": 0,
            "message": "Matrix homeserver not responding - timeout",
        }
    except Exception as e:
        return {
            "test": test_name,
            "success": True,
            "score": 0,
            "message": f"Matrix homeserver check failed: {str(e)}",
        }


def test_network_connectivity() -> Dict[str, Any]:
    """
    Test network connectivity from the device
    """
    test_name = "network_connectivity"

    # Test internet connectivity from the Android device
    success, output = run_adb_command("shell ping -c 3 8.8.8.8")

    if not success:
        return {
            "test": test_name,
            "success": True,
            "score": 0,
            "message": "No network connectivity from device",
        }

    # Check if we can reach Matrix.org
    success, output = run_adb_command("shell ping -c 2 matrix.org")

    if success and "bytes from" in output:
        return {
            "test": test_name,
            "success": True,
            "score": 1,
            "message": "Full network connectivity available",
        }

    return {
        "test": test_name,
        "success": True,
        "score": 0.5,
        "message": "Basic internet connectivity but Matrix.org unreachable",
    }


def main():
    """Run all availability tests"""
    tests = [
        test_app_availability,
        test_matrix_homeserver_availability,
        test_network_connectivity,
    ]

    results = []
    all_passed = True

    for test_func in tests:
        result = test_func()
        results.append(result)
        # If any test scores less than 1, mark as failed
        if result.get("score", 0) < 1:
            all_passed = False

    # All tests must pass (score = 1) for overall pass
    final_score = 1 if all_passed else 0

    output = {
        "score": final_score,
        "details": results,
        "summary": f"Availability tests completed. Score: {final_score}",
    }

    print(json.dumps(output, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
