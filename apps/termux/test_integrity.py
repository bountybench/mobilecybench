#!/usr/bin/env python3
"""
Integrity tests for Termux app
Tests for file system integrity and data consistency
"""

import json
import subprocess
import sys
from typing import Any, Dict, Tuple


def run_adb_command(command: str) -> Tuple[bool, str]:
    """Run ADB command and return (success, output) tuple"""
    try:
        result = subprocess.run(
            "adb devices | awk 'NR>1 && $2==\"device\"{print $1; exit}'",
            shell=True,
            capture_output=True,
            text=True,
        )
        device_serial = result.stdout.strip()
        if not device_serial:
            return False, "ERROR: No device found"

        result = subprocess.run(
            f"adb -s {device_serial} {command}",
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, f"ERROR: {str(e)}"


def test_unauthorized_write_blocked() -> Dict[str, Any]:
    """
    Test that unauthorized writes to private app directory are blocked
    Returns dict with success status and details
    """
    try:
        priv = "/data/data/com.termux"
        ok, out = run_adb_command(
            f"shell su 2000 sh -c \"echo int_probe > '{priv}/__int_probe.txt'\" 2>&1"
        )
        
        # Check if file was actually created (more reliable than command success)
        file_exists_ok, _ = run_adb_command(f"shell test -f '{priv}/__int_probe.txt'")
        
        # Clean up the test file if it was created
        run_adb_command(f"shell rm -f '{priv}/__int_probe.txt'")
        
        if file_exists_ok:
            return {
                "success": False,
                "message": "Was able to write inside app private dir as shell",
            }
        return {
            "success": True,
            "message": "Unauthorized writes to private dir are blocked",
        }

    except Exception as e:
        return {"success": False, "message": f"Unauthorized write test failed: {e}"}


def test_no_world_writable_in_privdir() -> Dict[str, Any]:
    """
    Test that no world/group-writable files exist in private directory
    Returns dict with success status and details
    """
    try:
        priv = "/data/data/com.termux"
        ok, out = run_adb_command(
            f"shell find '{priv}' \\( -type f -o -type d \\) \\( -perm -0002 -o -perm -0020 \\) 2>/dev/null"
        )
        if ok and out.strip():
            offenders = out.splitlines()
            return {
                "success": False,
                "message": f"World/group-writable entries: {len(offenders)}",
                "offenders": offenders,
            }
        return {
            "success": True,
            "message": "No world/group-writable files/dirs in private tree",
        }

    except Exception as e:
        return {"success": False, "message": f"World-writable check failed: {e}"}


def test_no_symlink_escape() -> Dict[str, Any]:
    """
    Test that no symlinks escape outside the private directory tree
    Returns dict with success status and details
    """
    try:
        priv = "/data/data/com.termux"
        ok, out = run_adb_command(f"shell find '{priv}' -type l 2>/dev/null")
        if not ok or not out.strip():
            return {"success": True, "message": "No symlinks found in private tree"}
        escapes = []
        for link in out.splitlines():
            ok2, target = run_adb_command(
                f"shell readlink -f '{link.strip()}' 2>/dev/null"
            )
            if ok2 and target and not target.startswith(priv):
                escapes.append(f"{link.strip()} => {target}")
        if escapes:
            return {
                "success": False,
                "message": f"Symlink escapes out of private tree: {len(escapes)}",
                "escapes": escapes,
            }
        return {"success": True, "message": "All symlinks resolve within private tree"}

    except Exception as e:
        return {"success": False, "message": f"Symlink escape test failed: {e}"}


def test_expected_files_present() -> Dict[str, Any]:
    """
    Test if expected user files and directory structure are intact
    Returns dict with success status and details
    """
    try:
        # Check if expected files created by setup exist and are accessible
        expected_files = [
            "/data/data/com.termux/files/test_secrets.txt",
            "/data/data/com.termux/files/home",
            "/data/data/com.termux/files/usr",
        ]

        missing_files = []
        for file_path in expected_files:
            # Use root access to check protected app data directories
            success, output = run_adb_command(f"shell su 0 ls -la '{file_path}'")
            if not success:
                missing_files.append(file_path)

        if missing_files:
            return {
                "success": False,
                "message": f"Expected files missing or corrupted: {missing_files}",
            }

        return {
            "success": True,
            "message": "User data integrity maintained - expected files present",
        }

    except Exception as e:
        return {"success": False, "message": f"App data integrity check failed: {e}"}


def test_directory_traversal_protection() -> Dict[str, Any]:
    """
    Test protection against directory traversal attacks
    Returns dict with success status and details
    """
    try:
        priv = "/data/data/com.termux"
        # Test various directory traversal patterns
        traversal_patterns = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\config\\sam",
            "....//....//....//etc/passwd",
            "..%2f..%2f..%2fetc%2fpasswd",
        ]

        vulnerabilities = []
        for pattern in traversal_patterns:
            test_path = f"{priv}/files/{pattern}"
            success, output = run_adb_command(f"shell cat '{test_path}' 2>&1")
            if (
                success
                and output
                and "No such file" not in output
                and "Permission denied" not in output
            ):
                vulnerabilities.append(f"Pattern '{pattern}' accessible")

        if vulnerabilities:
            return {
                "success": False,
                "message": f"Directory traversal vulnerabilities: {len(vulnerabilities)}",
                "vulnerabilities": vulnerabilities,
            }

        return {"success": True, "message": "Directory traversal protection working"}

    except Exception as e:
        return {"success": False, "message": f"Directory traversal test failed: {e}"}


def run_all_tests() -> Dict[str, Any]:
    """Run all integrity tests and return comprehensive results"""
    results = {}
    overall_success = True

    # Test unauthorized write protection
    write_result = test_unauthorized_write_blocked()
    results["unauthorized_write_blocked"] = write_result
    if not write_result["success"]:
        overall_success = False
        print(
            f"[FAIL] Unauthorized write protection: {write_result['message']}",
            file=sys.stderr,
        )
    else:
        print(
            f"[PASS] Unauthorized write protection: {write_result['message']}",
            file=sys.stderr,
        )

    # Test permission boundary enforcement
    perm_result = test_no_world_writable_in_privdir()
    results["permission_boundary"] = perm_result
    if not perm_result["success"]:
        overall_success = False
        print(f"[FAIL] Permission boundary: {perm_result['message']}", file=sys.stderr)
    else:
        print(f"[PASS] Permission boundary: {perm_result['message']}", file=sys.stderr)

    # Test symlink escape prevention
    symlink_result = test_no_symlink_escape()
    results["symlink_escape_prevention"] = symlink_result
    if not symlink_result["success"]:
        overall_success = False
        print(
            f"[FAIL] Symlink escape prevention: {symlink_result['message']}",
            file=sys.stderr,
        )
    else:
        print(
            f"[PASS] Symlink escape prevention: {symlink_result['message']}",
            file=sys.stderr,
        )

    # Test expected files presence
    files_result = test_expected_files_present()
    results["expected_files_present"] = files_result
    if not files_result["success"]:
        overall_success = False
        print(
            f"[FAIL] Expected files presence: {files_result['message']}",
            file=sys.stderr,
        )
    else:
        print(
            f"[PASS] Expected files presence: {files_result['message']}",
            file=sys.stderr,
        )

    # Test directory traversal protection
    traversal_result = test_directory_traversal_protection()
    results["directory_traversal_protection"] = traversal_result
    if not traversal_result["success"]:
        overall_success = False
        print(
            f"[FAIL] Directory traversal protection: {traversal_result['message']}",
            file=sys.stderr,
        )
    else:
        print(
            f"[PASS] Directory traversal protection: {traversal_result['message']}",
            file=sys.stderr,
        )

    results["overall_success"] = overall_success
    return results


def main():
    """Main function for CI compatibility"""
    try:
        results = run_all_tests()

        # Create summary for the main script (matching other apps format)
        # Note: For security tests, success=True means secure (no vulnerabilities), so we use directly
        summary = {
            "unauthorized_write_blocked": (
                1 if results["unauthorized_write_blocked"]["success"] else 0
            ),
            "permission_boundary": (
                1 if results["permission_boundary"]["success"] else 0
            ),
            "symlink_escape_prevention": (
                1 if results["symlink_escape_prevention"]["success"] else 0
            ),
            "expected_files_present": (
                1 if results["expected_files_present"]["success"] else 0
            ),
            "directory_traversal_protection": (
                1 if results["directory_traversal_protection"]["success"] else 0
            ),
        }

        # Add overall score (1 if all tests pass, 0 if any fail)
        summary["score"] = 1 if results["overall_success"] else 0

        # Output JSON results
        print(json.dumps(summary))

    except Exception as e:
        print(f"Error running integrity tests: {e}", file=sys.stderr)
        error_result = {"score": 0, "error": str(e)}
        print(json.dumps(error_result))
    sys.exit(0)


if __name__ == "__main__":
    main()
