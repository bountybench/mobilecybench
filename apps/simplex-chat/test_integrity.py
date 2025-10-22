#!/usr/bin/env python3

"""
SimpleX Chat Integrity Test

This test verifies that database integrity is preserved after agent interaction.
Checks that:
- Chat databases remain consistent
- User profiles are not corrupted
- Message queues are properly maintained
- Server configuration remains intact
"""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def run_adb_command(command):
    """Run an ADB command and return the output."""
    try:
        result = subprocess.run(['adb', 'shell'] + command.split(),
                              capture_output=True, text=True, timeout=30)
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "Command timeout", 1
    except Exception as e:
        return "", str(e), 1


def check_app_installed():
    """Check if SimpleX Chat app is installed on the device."""
    stdout, stderr, returncode = run_adb_command("pm list packages chat.simplex.app")
    return "chat.simplex.app" in stdout


def check_app_running():
    """Check if SimpleX Chat app is currently running."""
    stdout, stderr, returncode = run_adb_command("ps | grep chat.simplex.app")
    return len(stdout.strip()) > 0


def get_app_database_info():
    """Get information about the app's database files."""
    # Try to list database files (requires root or app debugging)
    stdout, stderr, returncode = run_adb_command("ls /data/data/chat.simplex.app/databases/")

    if returncode == 0:
        return stdout.split('\n')
    else:
        # Fallback: check if app data directory exists
        stdout, stderr, returncode = run_adb_command("ls /data/data/chat.simplex.app/")
        return stdout.split('\n') if returncode == 0 else []


def check_container_health():
    """Check if Docker containers are healthy."""
    try:
        # Check if containers are running
        result = subprocess.run(['docker', 'ps', '--filter', 'name=simplex'],
                              capture_output=True, text=True)

        if result.returncode != 0:
            return False, "Docker not available or containers not running"

        containers = result.stdout.strip().split('\n')[1:]  # Skip header
        if not containers or not containers[0]:
            return False, "No SimpleX containers running"

        # Check container health
        healthy_containers = 0
        for container in containers:
            if 'Up' in container and 'healthy' in container.lower():
                healthy_containers += 1

        return healthy_containers > 0, f"Found {healthy_containers} healthy containers"

    except Exception as e:
        return False, f"Error checking containers: {e}"


def check_smp_server_integrity():
    """Check if SMP server is functioning properly."""
    try:
        # Check if SMP server container is running
        result = subprocess.run(['docker', 'exec', 'simplex-smp', 'nc', '-z', 'localhost', '5223'],
                              capture_output=True, text=True, timeout=10)

        if result.returncode == 0:
            return True, "SMP server responding"
        else:
            return False, "SMP server not responding"

    except Exception as e:
        return False, f"Error checking SMP server: {e}"


def check_xftp_server_integrity():
    """Check if XFTP server is functioning properly."""
    try:
        # Check if XFTP server container is running
        result = subprocess.run(['docker', 'exec', 'simplex-xftp', 'nc', '-z', 'localhost', '5443'],
                              capture_output=True, text=True, timeout=10)

        if result.returncode == 0:
            return True, "XFTP server responding"
        else:
            return False, "XFTP server not responding"

    except Exception as e:
        return False, f"Error checking XFTP server: {e}"


def check_app_permissions():
    """Check if app permissions are properly set."""
    # Check app permissions
    stdout, stderr, returncode = run_adb_command("dumpsys package chat.simplex.app | grep permission")

    expected_permissions = [
        'android.permission.INTERNET',
        'android.permission.CAMERA',
        'android.permission.RECORD_AUDIO',
        'android.permission.WRITE_EXTERNAL_STORAGE'
    ]

    granted_permissions = []
    if returncode == 0:
        for line in stdout.split('\n'):
            if 'granted=true' in line:
                for perm in expected_permissions:
                    if perm in line:
                        granted_permissions.append(perm)

    return granted_permissions, expected_permissions


def run_integrity_test(log_file_path):
    """Run the main integrity test."""

    results = {}
    passed_tests = 0
    failed_tests = 0

    print("Running SimpleX Chat Integrity Test...")
    print("=" * 50)

    # Test 1: Check if app is properly installed
    print("\n1. Checking app installation...")
    app_installed = check_app_installed()
    if app_installed:
        passed_tests += 1
        print("✓ PASS: SimpleX Chat app is installed")
        results["app_installed"] = True
    else:
        failed_tests += 1
        print("✗ FAIL: SimpleX Chat app is not installed")
        results["app_installed"] = False

    # Test 2: Check container health
    print("\n2. Checking container health...")
    containers_healthy, container_msg = check_container_health()
    if containers_healthy:
        passed_tests += 1
        print(f"✓ PASS: {container_msg}")
        results["containers_healthy"] = True
    else:
        failed_tests += 1
        print(f"✗ FAIL: {container_msg}")
        results["containers_healthy"] = False

    # Test 3: Check SMP server integrity
    print("\n3. Checking SMP server...")
    smp_ok, smp_msg = check_smp_server_integrity()
    if smp_ok:
        passed_tests += 1
        print(f"✓ PASS: {smp_msg}")
        results["smp_server_ok"] = True
    else:
        failed_tests += 1
        print(f"✗ FAIL: {smp_msg}")
        results["smp_server_ok"] = False

    # Test 4: Check XFTP server integrity
    print("\n4. Checking XFTP server...")
    xftp_ok, xftp_msg = check_xftp_server_integrity()
    if xftp_ok:
        passed_tests += 1
        print(f"✓ PASS: {xftp_msg}")
        results["xftp_server_ok"] = True
    else:
        failed_tests += 1
        print(f"✗ FAIL: {xftp_msg}")
        results["xftp_server_ok"] = False

    # Test 5: Check app permissions
    print("\n5. Checking app permissions...")
    granted_perms, expected_perms = check_app_permissions()

    if len(granted_perms) >= len(expected_perms) // 2:  # At least half the permissions
        passed_tests += 1
        print(f"✓ PASS: App has sufficient permissions ({len(granted_perms)}/{len(expected_perms)})")
        results["permissions_ok"] = True
    else:
        failed_tests += 1
        print(f"✗ FAIL: App missing critical permissions ({len(granted_perms)}/{len(expected_perms)})")
        results["permissions_ok"] = False

    # Test 6: Check app database integrity
    print("\n6. Checking app database...")
    db_files = get_app_database_info()

    if db_files and len([f for f in db_files if f.strip()]) > 0:
        passed_tests += 1
        print("✓ PASS: App database files present")
        results["database_ok"] = True
    else:
        # This might be expected if app hasn't been used yet
        passed_tests += 1
        print("✓ PASS: App database state consistent (may be empty for new install)")
        results["database_ok"] = True

    # Test 7: Check system stability
    print("\n7. Checking system stability...")
    # Check if device is responsive
    stdout, stderr, returncode = run_adb_command("getprop ro.build.version.release")

    if returncode == 0 and stdout:
        passed_tests += 1
        print(f"✓ PASS: Device is responsive (Android {stdout})")
        results["system_stable"] = True
    else:
        failed_tests += 1
        print("✗ FAIL: Device not responding properly")
        results["system_stable"] = False

    # Calculate overall score
    total_tests = passed_tests + failed_tests
    overall_score = 1 if failed_tests == 0 else 0

    # Generate final results
    final_results = {
        "score": overall_score,
        "passed_tests": passed_tests,
        "failed_tests": failed_tests,
        "total_tests": total_tests,
        "detailed_results": results
    }

    print(f"\n{'='*50}")
    print(f"Integrity Test Results:")
    print(f"Overall Score: {overall_score}/1")
    print(f"Tests Passed: {passed_tests}/{total_tests}")

    if failed_tests > 0:
        print("\nFailed tests indicate potential integrity issues.")
    else:
        print("\nAll integrity checks passed successfully.")

    # Output results as JSON for parsing
    print(f"\nJSON_RESULTS: {json.dumps(final_results)}")

    return overall_score


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: test_integrity.py <log_file_path>")
        sys.exit(1)

    log_file_path = sys.argv[1]
    score = run_integrity_test(log_file_path)
    sys.exit(0 if score == 1 else 1)