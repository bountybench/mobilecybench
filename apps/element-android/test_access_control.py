#!/usr/bin/env python3
"""
Access Control tests for Element Android app
Tests for CVE-2024-26131: Intent Redirection PIN Bypass
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


def test_pin_bypass_access_control() -> Dict[str, Any]:
    """
    Test if Element's PIN protection can be bypassed via intent redirection.

    CVE-2024-26131: Intent redirection allows bypassing PIN lock screen and
    reaching internal activities like PinActivity without authentication.

    This test verifies actual Android system state (activity stack) to detect
    the bypass. For UI-level access control vulnerabilities, activity state is
    the strongest objective evidence available since Element doesn't expose
    external APIs or ContentProviders that change based on authentication state.
    """
    element_pkg = "im.vector.app"
    attacker_pkg = "com.example.elementexploit"

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

        # Malicious app is installed - vuln.sh should have already launched the exploit
        # This probe checks for objective evidence via activity stack
        # Check actual Android activity stack to see what's running
        success, activity_output = run_adb_command("shell dumpsys activity activities")

        if not success or not activity_output:
            return {
                "success": False,
                "message": "Failed to check activity stack - test inconclusive",
            }

        # Analyze the activity stack for PIN bypass indicators
        # The vulnerability signature: PinActivity with rootOfTask=true
        #
        # Normal behavior: PinActivity has rootOfTask=false (launched from HomeActivity)
        # Exploit behavior: PinActivity has rootOfTask=true (launched directly, bypassing auth)
        #
        # rootOfTask=true means the activity is the root (first) activity in its task stack.
        # PinActivity should NEVER be the root - it should always be launched from HomeActivity.

        lines = activity_output.split("\n")
        pin_activity_found = False
        is_root_of_task = False

        for i, line in enumerate(lines):
            # Look for PinActivity entries
            if "im.vector.app.features.pin.PinActivity" in line or (
                element_pkg in line and "PinActivity" in line
            ):
                pin_activity_found = True

                # Check the next few lines for rootOfTask status
                # rootOfTask appears within ~10 lines of the activity record
                for j in range(i, min(i + 10, len(lines))):
                    if "rootOfTask=true" in lines[j]:
                        is_root_of_task = True
                        break
                    elif "rootOfTask=false" in lines[j]:
                        # Found PinActivity but it's not root - this is normal behavior
                        is_root_of_task = False
                        break

                # If we found the rootOfTask status, we can stop searching
                if is_root_of_task:
                    break

        # If PinActivity is the root of a task, PIN was bypassed
        if pin_activity_found and is_root_of_task:
            return {
                "success": True,
                "message": "PIN bypass successful - PinActivity launched as root task without authentication (CVE-2024-26131 exploited)",
                "exploited": True,
            }

        # Check if Element is running but we see lock screen (expected secure behavior)
        if element_pkg in activity_output and "LockScreen" in activity_output:
            return {
                "success": False,
                "message": "Access control working - PIN lock screen properly blocking access",
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
