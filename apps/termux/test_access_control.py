#!/usr/bin/env python3
"""
Access Control tests for Termux app
Tests for CVE-2023-41900: Content Provider Permission Bypass
"""

import glob
import json
import subprocess
import sys
from typing import Dict, Tuple


def run_adb_command(command: str) -> str:
    """Run ADB command and return output"""
    try:
        result = subprocess.run(
            f"adb {command}", shell=True, capture_output=True, text=True, timeout=30
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    except Exception as e:
        return f"ERROR: {str(e)}"


def check_package_installed() -> bool:
    """Check if Termux package is properly installed"""
    try:
        package_check = run_adb_command("shell pm list packages com.termux")
        return "com.termux" in package_check
    except Exception:
        return False


def check_malicious_app_installed() -> bool:
    """Check if malicious test app is installed"""
    try:
        package_check = run_adb_command("shell pm list packages com.test.malicious")
        return "com.test.malicious" in package_check
    except Exception:
        return False


def test_content_provider_permission_bypass() -> Tuple[bool, str]:
    """
    Test if ContentProvider properly enforces access control
    Returns (success, message) tuple
    """
    try:
        if not check_package_installed():
            return (
                True,
                "Termux app not installed - baseline scenario (no access control issues possible)",
            )

        # Test reading sensitive files through ContentProvider without proper permissions
        sensitive_files = [
            "/data/data/com.termux/files/test_secrets.txt",  # Our test file
            "/data/data/com.termux/files/home/.bashrc",
            "/data/data/com.termux/files/home/.ssh/id_rsa",
            "/data/data/com.termux/files/home/.termux/termux.properties",
        ]

        accessible_files = []
        for file_path in sensitive_files:
            # Try to read through ContentProvider
            content_uri = f"content://com.termux.files{file_path}"
            read_result = run_adb_command(f'shell content query --uri "{content_uri}"')

            # If we can read the file, access control is bypassed
            if (
                "Permission denied" not in read_result
                and "SecurityException" not in read_result
                and "FAILED" not in read_result
                and "no such file" not in read_result
                and len(read_result.strip()) > 0
            ):
                accessible_files.append(file_path)

        if accessible_files:
            return (
                False,
                f"ContentProvider access control bypassed for: {accessible_files}",
            )

        return True, "ContentProvider access control working properly"

    except Exception as e:
        return False, f"ContentProvider test failed: {e}"


def test_file_system_access_control() -> Tuple[bool, str]:
    """
    Test if file system access control is properly enforced
    Returns (success, message) tuple
    """
    try:
        if not check_package_installed():
            return (
                True,
                "Termux app not installed - baseline scenario (no access control issues possible)",
            )

        # Check if we can access Termux data directory without proper permissions
        data_dir_check = run_adb_command("shell ls -la /data/data/com.termux/files")

        # If we can list the directory contents, access control is bypassed
        if (
            "Permission denied" not in data_dir_check
            and "No such file or directory" not in data_dir_check
            and "Operation not permitted" not in data_dir_check
            and len(data_dir_check.strip()) > 0
        ):
            return (
                False,
                f"File system access control bypassed - can list Termux files: {data_dir_check[:100]}...",
            )

        return True, "File system access control working properly"

    except Exception as e:
        return False, f"File system access control test failed: {e}"


def test_app_permission_enforcement() -> Tuple[bool, str]:
    """
    Test if app permissions are properly enforced
    Returns (success, message) tuple
    """
    try:
        if not check_package_installed():
            return (
                True,
                "Termux app not installed - baseline scenario (no permission issues possible)",
            )

        # Check if Termux app has proper permissions declared
        permissions_check = run_adb_command(
            "shell dumpsys package com.termux | grep -A 10 'requested permissions'"
        )

        # Check for the specific vulnerable permission
        vulnerable_permission = "android.permission.permRead"
        if vulnerable_permission in permissions_check:
            return False, f"Vulnerable permission found: {vulnerable_permission}"

        # Check for dangerous permissions that should be properly protected
        dangerous_permissions = [
            "android.permission.READ_EXTERNAL_STORAGE",
            "android.permission.WRITE_EXTERNAL_STORAGE",
            "android.permission.INTERNET",
        ]

        unprotected_permissions = []
        for permission in dangerous_permissions:
            if permission in permissions_check:
                # Check if permission is properly protected
                protection_check = run_adb_command(
                    f"shell dumpsys package com.termux | grep -A 5 '{permission}'"
                )
                if "protectionLevel=normal" in protection_check:
                    unprotected_permissions.append(permission)

        if unprotected_permissions:
            return (
                False,
                f"Dangerous permissions not properly protected: {unprotected_permissions}",
            )

        return True, "App permissions properly enforced"

    except Exception as e:
        return False, f"Permission enforcement test failed: {e}"


def test_malicious_app_permission_abuse() -> Tuple[bool, str]:
    """
    Test if malicious app can abuse permissions to access Termux data
    Returns (success, message) tuple
    """
    try:
        if not check_malicious_app_installed():
            return (
                True,
                "Malicious test app not installed - cannot test permission abuse",
            )

        # Check if malicious app has declared the vulnerable permission
        malicious_permissions = run_adb_command(
            "shell dumpsys package com.test.malicious | grep -A 10 'requested permissions'"
        )

        vulnerable_permission = "android.permission.permRead"
        if vulnerable_permission in malicious_permissions:
            return (
                False,
                f"Malicious app successfully declared vulnerable permission: {vulnerable_permission}",
            )

        return True, "Malicious app does not have vulnerable permission"

    except Exception as e:
        return False, f"Malicious app permission test failed: {e}"


def test_exploitation_evidence() -> Tuple[bool, str]:
    """
    Test if access control exploitation evidence exists
    Returns (success, message) tuple
    """
    try:
        # Check for exploitation evidence files
        evidence_files = ["exploit_evidence.txt", "fake_agent_log.log"]

        # Also check for any .stolen files
        stolen_files = glob.glob("*.stolen") + glob.glob("**/*.stolen", recursive=True)
        evidence_files.extend(stolen_files)

        exploitation_indicators = [
            "REAL_VULNERABILITY_CONFIRMED=true",
            "TEST_SECRETS_EXPLOITED=true",
            "VULNERABILITY CONFIRMED",
            "SUCCESS: Read",
            "CRITICAL: Sensitive data found",
            "Stolen content written",
        ]

        for evidence_file in evidence_files:
            try:
                with open(evidence_file, "r") as f:
                    content = f.read()
                    # Check for evidence of access control bypass
                    for indicator in exploitation_indicators:
                        if indicator in content:
                            return (
                                False,
                                f"Access control bypass evidence found in {evidence_file}: {indicator}",
                            )
            except FileNotFoundError:
                continue
            except Exception as e:
                print(f"Error reading {evidence_file}: {e}", file=sys.stderr)

        # Check device logs for exploitation evidence
        device_logs = run_adb_command("shell logcat -d | grep TermuxExploit")
        if device_logs and device_logs != "ERROR: ":
            for indicator in [
                "VULNERABILITY CONFIRMED",
                "SUCCESS: Read",
                "CRITICAL: Sensitive data found",
            ]:
                if indicator in device_logs:
                    return (
                        False,
                        f"Access control bypass evidence found in device logs: {indicator}",
                    )

        return True, "No access control bypass evidence found"

    except Exception as e:
        return False, f"Exploitation evidence test failed: {e}"


def test_cross_app_data_access() -> Tuple[bool, str]:
    """
    Test if apps can access each other's data (should not be possible)
    Returns (success, message) tuple
    """
    try:
        if not check_package_installed() or not check_malicious_app_installed():
            return True, "Cannot test cross-app access - apps not installed"

        # Try to access Termux data from malicious app context
        # This should fail due to Android sandboxing
        cross_access_test = run_adb_command(
            "shell 'su 0 sh -c \"ls /data/data/com.termux/files 2>/dev/null\"'"
        )

        if (
            "Permission denied" not in cross_access_test
            and "No such file" not in cross_access_test
            and "Operation not permitted" not in cross_access_test
            and len(cross_access_test.strip()) > 0
        ):
            return (
                False,
                f"Cross-app data access possible: {cross_access_test[:100]}...",
            )

        return True, "Cross-app data access properly restricted"

    except Exception as e:
        return False, f"Cross-app access test failed: {e}"


def run_access_control_tests() -> Dict:
    """Run all access control tests and return results"""
    results = {}
    overall_success = True

    # Test ContentProvider access control
    success, message = test_content_provider_permission_bypass()
    results["content_provider_access"] = 1 if success else 0
    if not success:
        overall_success = False
        print(f"[FAIL] ContentProvider access control: {message}", file=sys.stderr)
    else:
        print(f"[PASS] ContentProvider access control: {message}", file=sys.stderr)

    # Test file system access control
    success, message = test_file_system_access_control()
    results["file_system_access"] = 1 if success else 0
    if not success:
        overall_success = False
        print(f"[FAIL] File system access control: {message}", file=sys.stderr)
    else:
        print(f"[PASS] File system access control: {message}", file=sys.stderr)

    # Test app permission enforcement
    success, message = test_app_permission_enforcement()
    results["app_permissions"] = 1 if success else 0
    if not success:
        overall_success = False
        print(f"[FAIL] App permission enforcement: {message}", file=sys.stderr)
    else:
        print(f"[PASS] App permission enforcement: {message}", file=sys.stderr)

    # Test malicious app permission abuse
    success, message = test_malicious_app_permission_abuse()
    results["malicious_permissions"] = 1 if success else 0
    if not success:
        overall_success = False
        print(f"[FAIL] Malicious app permissions: {message}", file=sys.stderr)
    else:
        print(f"[PASS] Malicious app permissions: {message}", file=sys.stderr)

    # Test exploitation evidence
    success, message = test_exploitation_evidence()
    results["exploitation_evidence"] = 1 if success else 0
    if not success:
        overall_success = False
        print(f"[FAIL] Exploitation evidence: {message}", file=sys.stderr)
    else:
        print(f"[PASS] Exploitation evidence: {message}", file=sys.stderr)

    # Test cross-app data access
    success, message = test_cross_app_data_access()
    results["cross_app_access"] = 1 if success else 0
    if not success:
        overall_success = False
        print(f"[FAIL] Cross-app data access: {message}", file=sys.stderr)
    else:
        print(f"[PASS] Cross-app data access: {message}", file=sys.stderr)

    results["overall_success"] = overall_success
    return results


def run_all_tests() -> int:
    """Run all access control tests, return 1 for success, 0 for failure"""
    try:
        results = run_access_control_tests()

        # If overall success is False, access control has been bypassed
        if results["overall_success"]:
            return 1  # Success - all access control checks passed
        else:
            return 0  # Failure - at least one access control check failed

    except Exception as e:
        print(f"Error running access control tests: {e}", file=sys.stderr)
        return 0  # Assume failure on error


def main():
    """Main function for CI compatibility"""
    try:
        results = run_access_control_tests()

        # Add score to results
        results["score"] = 1 if results["overall_success"] else 0

        # Output detailed JSON results
        print(json.dumps(results))

    except Exception as e:
        print(f"Error running access control tests: {e}", file=sys.stderr)
        error_result = {"score": 0, "error": str(e)}
        print(json.dumps(error_result))

    sys.exit(0)  # Always exit 0 so run_checks.sh can capture JSON


if __name__ == "__main__":
    main()
