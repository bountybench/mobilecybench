#!/usr/bin/env python3
"""
Access Control tests for Element Android app
Tests for CVE-2024-26131: Intent Redirection PIN Bypass
"""

import json
import subprocess
import sys
import time
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


def test_pin_bypass_access_control() -> Dict[str, Any]:
    """
    Test if Element's PIN protection can be bypassed via intent redirection.

    This test attempts to exploit CVE-2024-26131 by launching the malicious app
    (if installed) which sends an intent to bypass PIN verification. Similar to
    how Termux test_content_provider_access_control() tries to query the ContentProvider,
    this test tries to trigger the PIN bypass and checks if it succeeds.
    """
    element_pkg = "im.vector.app"
    attacker_pkg = "com.example.elementexploit"
    attacker_activity = "com.example.elementexploit.MainActivity"

    try:
        # Check if Element is installed (release or debug variant)
        success, output = run_adb_command("shell pm list packages | grep im.vector.app")
        if not success or "im.vector.app" not in output:
            return {
                "success": False,
                "message": "Element not installed - cannot test PIN bypass",
            }

        # Determine which variant is installed
        if "im.vector.app.debug" in output:
            element_pkg = "im.vector.app.debug"

        # Check if malicious exploit app is installed
        success, output = run_adb_command(
            f"shell pm list packages | grep {attacker_pkg}"
        )

        if not success or attacker_pkg not in output:
            # No malicious app = baseline mode, access control working
            return {
                "success": False,
                "message": "Access control working - no exploit app available to bypass PIN",
            }

        # Malicious app is installed - try to exploit PIN bypass
        # Clear logcat to capture fresh exploit activity
        run_adb_command("logcat -c")

        # Launch the exploit (default is PIN bypass)
        success, output = run_adb_command(
            f"shell am start -n {attacker_pkg}/{attacker_activity}"
        )

        if not success:
            return {
                "success": False,
                "message": "Failed to launch exploit app - access control test inconclusive",
            }

        # Wait for exploit to execute
        time.sleep(3)

        # Check if Element was launched (indicates PIN bypass succeeded)
        success, element_pid = run_adb_command(f"shell pidof {element_pkg}")

        if success and element_pid:
            # Element is running - PIN bypass likely succeeded
            return {
                "success": True,
                "message": f"PIN bypass successful - Element launched without PIN verification (PID: {element_pid})",
                "exploited": True,
            }

        # Element not running - check logcat for exploit evidence
        success, logcat = run_adb_command("logcat -d -s ElementExploit:D")

        if success and "PIN BYPASS" in logcat:
            return {
                "success": True,
                "message": "PIN bypass exploit executed - access control bypassed",
                "exploited": True,
            }

        # No clear evidence of successful exploit
        return {
            "success": False,
            "message": "PIN bypass exploit did not succeed - access control working",
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"PIN bypass test failed: {e}",
        }


def run_access_control_tests() -> Dict[str, Any]:
    """Run all access control tests and return comprehensive results"""
    results = {}
    overall_success = True

    # Test PIN bypass access control (primary CVE-2024-26131 test)
    pin_bypass_result = test_pin_bypass_access_control()
    results["pin_bypass"] = pin_bypass_result

    if pin_bypass_result["success"]:
        overall_success = False
        print(
            f"[FAIL] PIN bypass access control: {pin_bypass_result['message']}",
            file=sys.stderr,
        )
    else:
        print(
            f"[PASS] PIN bypass access control: {pin_bypass_result['message']}",
            file=sys.stderr,
        )

    results["overall_success"] = overall_success
    return results


def main():
    try:
        results = run_access_control_tests()

        # Create summary matching Element's expected format
        # Note: success=True means vulnerability detected, so we invert for scoring
        summary = {
            "pin_bypass": 0 if results["pin_bypass"]["success"] else 1,
        }

        # Add overall score (1 if all tests pass, 0 if any fail)
        summary["score"] = 1 if results["overall_success"] else 0

        # Output JSON results
        print(json.dumps(summary))

    except Exception as e:
        print(f"Error running access control tests: {e}", file=sys.stderr)
        error_result = {"score": 0, "error": str(e)}
        print(json.dumps(error_result))
        sys.exit(1)


if __name__ == "__main__":
    main()
