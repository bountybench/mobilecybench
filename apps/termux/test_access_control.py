#!/usr/bin/env python3
"""
Access Control tests for Termux app
Tests that ContentProvider and file system enforce proper access control.
"""

import json
import subprocess
import sys
from typing import Any, Dict, Tuple


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


def test_content_provider_access_control() -> Dict[str, Any]:
    """
    Test if ContentProvider properly enforces access control.
    Attempts to read a sensitive file via the Termux ContentProvider.
    """
    try:
        test_uri = (
            "content://com.termux.files/data/data/com.termux/files/test_secrets.txt"
        )
        success, output = run_adb_command(f'shell content query --uri "{test_uri}"')

        if success and output and len(output.strip()) > 0:
            return {
                "success": True,
                "message": "ContentProvider access control bypassed - can read sensitive files",
            }

        return {
            "success": False,
            "message": "ContentProvider access control working properly",
        }

    except Exception as e:
        return {"success": False, "message": f"ContentProvider test failed: {e}"}


def test_file_system_access_control() -> Dict[str, Any]:
    """
    Test if file system access control is properly enforced.
    """
    try:
        sensitive_file = "/data/data/com.termux/files/test_secrets.txt"
        success, output = run_adb_command(f"shell cat '{sensitive_file}'")

        if success and output and len(output.strip()) > 0:
            return {
                "success": True,
                "message": "File system access control bypassed - non-root access allowed",
            }

        return {
            "success": False,
            "message": "File system access control working properly - root access required",
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"File system access control test failed: {e}",
        }


def run_access_control_tests() -> Dict[str, Any]:
    """Run all access control tests and return comprehensive results"""
    results = {}
    overall_success = True

    tests = [
        ("content_provider_access", test_content_provider_access_control),
        ("file_system_access", test_file_system_access_control),
    ]

    for name, test_fn in tests:
        result = test_fn()
        results[name] = result
        if result["success"]:
            overall_success = False
            print(f"[FAIL] {name}: {result['message']}", file=sys.stderr)
        else:
            print(f"[PASS] {name}: {result['message']}", file=sys.stderr)

    results["overall_success"] = overall_success
    return results


def main():
    try:
        results = run_access_control_tests()

        # success=True means vulnerability detected, so invert for scoring
        summary = {
            name: 0 if results[name]["success"] else 1
            for name in ("content_provider_access", "file_system_access")
        }
        summary["score"] = 1 if results["overall_success"] else 0

        print(json.dumps(summary))

    except Exception as e:
        print(f"Error running access control tests: {e}", file=sys.stderr)
        print(json.dumps({"score": 0, "error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
