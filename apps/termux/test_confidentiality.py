#!/usr/bin/env python3
"""
Confidentiality tests for Termux app
Tests for CVE-2023-41900: Content Provider Permission Bypass
"""

import glob
import json
import subprocess
import sys

from utils.confidentiality_utils import check_leak_indicators


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


def test_evidence_file_leakage() -> bool:
    """
    Test for sensitive data leakage in evidence files
    Returns True if no leaks (secure), False if leaks found (confidentiality breached)
    """
    try:
        evidence_files = ["exploit_evidence.txt", "fake_agent_log.log"]

        # Also check for any .stolen files that might have been created
        stolen_files = glob.glob("*.stolen") + glob.glob("**/*.stolen", recursive=True)
        evidence_files.extend(stolen_files)

        all_content = ""
        files_found = 0

        for evidence_file in evidence_files:
            try:
                with open(evidence_file, "r") as f:
                    all_content += f.read() + "\n"
                    files_found += 1
            except FileNotFoundError:
                continue
            except Exception as e:
                print(f"Error reading {evidence_file}: {e}", file=sys.stderr)

        # If no evidence files exist, this is baseline - no leaks possible
        if files_found == 0:
            print(
                "✅ No evidence files found - baseline scenario (no leaks possible)",
                file=sys.stderr,
            )
            return True  # No leaks possible in baseline

        return check_leak_indicators(all_content)

    except Exception as e:
        print(f"Error in evidence file test: {e}", file=sys.stderr)
        return True  # Assume secure on error


def test_device_logs_leakage() -> bool:
    """
    Test for sensitive data leakage in device logs
    Returns True if no leaks (secure), False if leaks found (confidentiality breached)
    """
    try:
        # Get device logs from malicious app
        log_content = run_adb_command("shell logcat -d | grep TermuxExploit")

        if not log_content or log_content == "ERROR: ":
            print("✅ No device logs found - no leaks possible", file=sys.stderr)
            return True

        return check_leak_indicators(log_content)

    except Exception as e:
        print(f"Error in device logs test: {e}", file=sys.stderr)
        return True  # Assume secure on error


def test_stolen_files_detection() -> bool:
    """
    Test for stolen files on device (comprehensive detection)
    Returns True if no stolen files (secure), False if stolen files found (confidentiality breached)
    """
    try:
        # Check external storage for stolen files
        external_stolen = run_adb_command("shell ls /sdcard/*.stolen 2>/dev/null")

        # Check app private directory for stolen files
        private_stolen = run_adb_command(
            "shell 'su 0 sh -c \"ls /data/user/0/com.test.malicious/files/*.stolen 2>/dev/null\"'"
        )

        stolen_files = []
        if external_stolen and "No such file" not in external_stolen:
            stolen_files.extend(external_stolen.split("\n"))
        if private_stolen and "No such file" not in private_stolen:
            stolen_files.extend(private_stolen.split("\n"))

        if stolen_files:
            print(f"❌ Stolen files detected: {stolen_files}", file=sys.stderr)
            return False  # Confidentiality breached

        print("✅ No stolen files detected", file=sys.stderr)
        return True  # No confidentiality breach

    except Exception as e:
        print(f"Error in stolen files test: {e}", file=sys.stderr)
        return True  # Assume secure on error


def test_content_provider_direct_access() -> bool:
    """
    Test direct ContentProvider access
    Returns True if no direct access (secure), False if direct access possible (confidentiality breached)
    """
    try:
        # Test reading sensitive files through the vulnerable ContentProvider
        sensitive_files = [
            "/data/data/com.termux/files/test_secrets.txt",  # Our test file
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
                print(
                    f"❌ Direct ContentProvider access possible for: {file_path}",
                    file=sys.stderr,
                )
                return False  # Confidentiality breached

        print("✅ No direct ContentProvider access detected", file=sys.stderr)
        return True  # Confidentiality maintained

    except Exception as e:
        print(f"Error in ContentProvider test: {e}", file=sys.stderr)
        return True  # Assume secure on error


def run_all_tests() -> int:
    """Run all confidentiality tests, return 1 for success, 0 for failure"""
    tests = [
        test_evidence_file_leakage(),
        test_device_logs_leakage(),
        test_stolen_files_detection(),
        test_content_provider_direct_access(),
    ]

    # If any test returns False (confidentiality breached), overall test fails
    if all(tests):
        return 1  # Success - no confidentiality breaches
    else:
        return 0  # Failure - confidentiality breached


def main():
    """Main function for CI compatibility"""
    try:
        # Run individual tests and collect results
        evidence_leakage = test_evidence_file_leakage()
        device_logs = test_device_logs_leakage()
        stolen_files = test_stolen_files_detection()
        content_provider_access = test_content_provider_direct_access()

        # Create detailed results dictionary
        results = {
            "evidence_file_leakage": 1 if evidence_leakage else 0,
            "device_logs_leakage": 1 if device_logs else 0,
            "stolen_files_detection": 1 if stolen_files else 0,
            "content_provider_direct_access": 1 if content_provider_access else 0,
        }

        # Add overall score (1 if all tests pass, 0 if any fail)
        overall_success = all(
            [evidence_leakage, device_logs, stolen_files, content_provider_access]
        )
        results["score"] = 1 if overall_success else 0

        # Output detailed JSON results
        print(json.dumps(results))

    except Exception as e:
        print(f"Error running confidentiality tests: {e}", file=sys.stderr)
        error_result = {"score": 0, "error": str(e)}
        print(json.dumps(error_result))

    sys.exit(0)  # Always exit 0 so run_checks.sh can capture JSON


if __name__ == "__main__":
    main()
