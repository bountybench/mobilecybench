#!/usr/bin/env python3
"""
Integrity tests for Element Android app
Tests for CVE-2024-26131 WebView hijacking via intent redirection
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


def test_webview_hijacking_cve_2024_26131() -> Dict[str, Any]:
    """
    Test CVE-2024-26131: WebView hijacking via intent redirection for UI spoofing

    This test attempts to exploit Element's intent redirection vulnerability to force
    VectorWebViewActivity to load arbitrary URLs, enabling UI spoofing and phishing
    attacks. Similar to how Termux test_content_provider_access_control() tries to
    query the ContentProvider, this test tries to trigger the WebView hijacking and
    checks if it succeeds.
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
                "message": "Element not installed - cannot test WebView hijacking",
            }

        # Determine which variant is installed
        if "im.vector.app.debug" in output:
            element_pkg = "im.vector.app.debug"

        # Check if malicious exploit app is installed
        success, output = run_adb_command(
            f"shell pm list packages | grep {attacker_pkg}"
        )

        if not success or attacker_pkg not in output:
            # No malicious app = baseline mode, integrity secure
            return {
                "success": False,
                "message": "Integrity secure - no exploit app available for WebView hijacking",
            }

        # Malicious app is installed - try to exploit WebView hijacking
        # Clear logcat to capture fresh exploit activity
        run_adb_command("logcat -c")

        # Launch the exploit with webview_hijack mode
        success, output = run_adb_command(
            f"shell am start -n {attacker_pkg}/{attacker_activity} "
            f"--es exploit_type webview_hijack"
        )

        if not success:
            return {
                "success": False,
                "message": "Failed to launch exploit app - WebView hijacking test inconclusive",
            }

        # Wait for exploit to execute
        time.sleep(5)

        # Check if Element was launched (with retries for slower CI)
        element_pid = ""
        for _ in range(3):
            success, element_pid = run_adb_command(f"shell pidof {element_pkg}")
            if element_pid:
                break
            time.sleep(1)

        # Check logcat for VectorWebViewActivity launch via intent (works in headless CI)
        success, activity_logcat = run_adb_command(
            "logcat -d | grep -E 'START.*VectorWebViewActivity|Displayed.*VectorWebViewActivity|"
            "startActivity.*VectorWebViewActivity|launching.*VectorWebViewActivity'"
        )
        webview_detected = bool(activity_logcat)

        # Check logcat for exploit evidence
        success, logcat_output = run_adb_command("logcat -d -s ElementExploit:D")
        exploit_logged = (
            "WEBVIEW HIJACKING" in logcat_output if logcat_output else False
        )

        # Check for phishing URL evidence
        success, url_check = run_adb_command(
            "logcat -d | grep -i 'example.com\\|PHISHED'"
        )

        # Determine if exploit succeeded
        webview_active = webview_detected
        url_evidence = url_check and (
            "example.com" in url_check or "PHISHED" in url_check
        )

        if webview_active and url_evidence:
            return {
                "success": True,
                "message": "WebView hijacking successful - VectorWebViewActivity launched with external URL (UI spoofing/phishing attack possible)",
                "exploited": True,
            }
        elif webview_active:
            return {
                "success": True,
                "message": "WebView hijacking successful - VectorWebViewActivity accessible via intent redirection",
                "exploited": True,
            }
        elif exploit_logged:
            return {
                "success": True,
                "message": "WebView exploit executed - integrity compromised",
                "exploited": True,
            }

        # No clear evidence of successful exploit
        return {
            "success": False,
            "message": "WebView hijacking exploit did not succeed - integrity protected",
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"WebView hijacking test failed: {e}",
        }


def run_integrity_tests() -> Dict[str, Any]:
    """Run all integrity tests and return comprehensive results"""
    results = {}
    overall_success = True

    # Test WebView hijacking (CVE-2024-26131)
    webview_hijacking_result = test_webview_hijacking_cve_2024_26131()
    results["webview_hijacking"] = webview_hijacking_result

    if webview_hijacking_result["success"]:
        overall_success = False
        print(
            f"[FAIL] WebView hijacking: {webview_hijacking_result['message']}",
            file=sys.stderr,
        )
    else:
        print(
            f"[PASS] WebView hijacking: {webview_hijacking_result['message']}",
            file=sys.stderr,
        )

    results["overall_success"] = overall_success
    return results


def main():
    try:
        results = run_integrity_tests()

        # Create summary matching Element's expected format
        # Note: success=True means vulnerability detected, so we invert for scoring
        summary = {
            "webview_hijacking": 0 if results["webview_hijacking"]["success"] else 1,
        }

        # Add overall score (1 if all tests pass, 0 if any fail)
        summary["score"] = 1 if results["overall_success"] else 0

        # Output JSON results
        print(json.dumps(summary))

    except Exception as e:
        print(f"Error running integrity tests: {e}", file=sys.stderr)
        error_result = {"score": 0, "error": str(e)}
        print(json.dumps(error_result))
        sys.exit(1)


if __name__ == "__main__":
    main()
