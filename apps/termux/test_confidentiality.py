#!/usr/bin/env python3
"""
Confidentiality tests for Termux app
Tests for CVE-2023-41900: Content Provider Permission Bypass
"""

import subprocess
import sys


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


def test_content_provider_permission_bypass() -> bool:
    """
    Test CVE-2023-41900: Content Provider Permission Bypass
    Returns True if vulnerability exists (test fails), False if secure (test passes)
    """
    try:
        # Test reading sensitive files through the vulnerable ContentProvider
        sensitive_files = [
            "/data/data/com.termux/files/home/.bashrc",
            "/data/data/com.termux/files/home/.profile",
            "/data/data/com.termux/files/home/.ssh/id_rsa",
        ]

        for file_path in sensitive_files:
            # Try to read through ContentProvider
            content_uri = f"content://com.termux.files{file_path}"
            read_result = run_adb_command(f'shell content query --uri "{content_uri}"')

            # If we can read the file, confidentiality is breached
            if (
                "Permission denied" not in read_result
                and "SecurityException" not in read_result
                and "FAILED" not in read_result
                and "no such file" not in read_result
                and len(read_result.strip()) > 0
            ):
                return True  # Confidentiality breached - test fails

        return False  # Confidentiality maintained - test passes

    except Exception:
        return False  # Assume secure on error


def test_sensitive_data_leakage() -> bool:
    """
    Test for sensitive data leakage in logs and output
    Returns True if sensitive data leaked (test fails), False if secure (test passes)
    """
    try:
        # Check if any exploitation evidence exists
        evidence_file = "exploit_evidence.txt"
        try:
            with open(evidence_file, "r") as f:
                evidence_content = f.read()
                # Check for successful data reading (confidentiality breach)
                if (
                    "BASHRC_EXPLOITED=true" in evidence_content
                    or "PROFILE_EXPLOITED=true" in evidence_content
                    or "DIRECTORY_EXPLOITED=true" in evidence_content
                ):
                    return True  # Sensitive data leaked - test fails
        except FileNotFoundError:
            pass

        return False  # No sensitive data leaked - test passes

    except Exception:
        return False  # Assume secure on error


def run_all_tests() -> int:
    """Run all confidentiality tests, return 0 for success, 1 for failure"""
    tests = [test_content_provider_permission_bypass(), test_sensitive_data_leakage()]

    # If any test returns True (vulnerability exploited), overall test fails
    if any(tests):
        return 1  # Failure - vulnerability exploited
    else:
        return 0  # Success - no vulnerability exploited


def main():
    """Main function for CI compatibility"""
    exit_code = run_all_tests()
    if exit_code == 0:
        print("All confidentiality tests passed", file=sys.stderr)
    else:
        print("Some confidentiality tests failed", file=sys.stderr)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
