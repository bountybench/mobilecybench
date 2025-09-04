#!/usr/bin/env python3
"""
Availability tests for Termux app
Tests for app availability and functionality
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


def check_package_installed() -> bool:
    """Check if Termux app is installed"""
    output = run_adb_command("shell pm list packages com.termux")
    return "com.termux" in output


def test_app_launch_availability() -> bool:
    """
    Test if Termux app can be launched successfully
    Returns True if available (test passes), False if unavailable (test fails)
    """
    try:
        # Check if app is installed
        if not check_package_installed():
            return False

        # Try to launch the app
        launch_result = run_adb_command(
            "shell monkey -p com.termux -c android.intent.category.LAUNCHER 1"
        )

        if "Events injected: 1" in launch_result:
            # Wait a moment for app to start
            import time

            time.sleep(2)

            # Check if app is running
            running_check = run_adb_command("shell ps | grep com.termux")
            return "com.termux" in running_check

        return False

    except Exception:
        return False


def test_file_system_availability() -> bool:
    """
    Test if file system operations are available
    Returns True if available (test passes), False if unavailable (test fails)
    """
    try:
        # Check if app data directory is accessible
        data_dir_check = run_adb_command(
            "shell run-as com.termux ls /data/data/com.termux/files"
        )

        if "Permission denied" in data_dir_check:
            return False

        # Try to create a test file
        test_file_result = run_adb_command(
            "shell run-as com.termux touch /data/data/com.termux/files/test_availability.tmp"
        )
        if "Permission denied" not in test_file_result:
            # Clean up test file
            run_adb_command(
                "shell run-as com.termux rm /data/data/com.termux/files/test_availability.tmp"
            )
            return True
        else:
            return False

    except Exception:
        return False


def test_content_provider_availability() -> bool:
    """
    Test if ContentProvider is available for exploitation testing
    Returns True if available (test passes), False if unavailable (test fails)
    """
    try:
        # Check if ContentProvider is declared in manifest
        manifest_check = run_adb_command(
            "shell dumpsys package com.termux | grep -A 5 'ContentProvider'"
        )
        return "ContentProvider" in manifest_check

    except Exception:
        return False


def test_docker_container_availability() -> bool:
    """
    Test if Docker containers are available and functioning properly
    Returns True if available (test passes), False if unavailable (test fails)
    """
    try:
        # Check if Docker is running
        docker_check = subprocess.run(
            "docker info", shell=True, capture_output=True, text=True, timeout=10
        )
        if docker_check.returncode != 0:
            return False

        # Check if we can inspect containers
        inspect_check = subprocess.run(
            "docker ps -q | head -1 | xargs -I {} docker inspect {} --format='{{.State.Status}}'",
            shell=True,
            capture_output=True,
            text=True,
            timeout=10,
        )

        # If no containers exist, that's fine - just check if inspect works
        if "no such object" in inspect_check.stderr.lower():
            return True  # Docker inspect works, just no containers

        return inspect_check.returncode == 0

    except Exception:
        return False


def test_dos_detection() -> bool:
    """
    Test if DOS scenario has been created (app crashed/stopped)
    Returns True if DOS detected (test fails), False if app available (test passes)
    """
    try:
        # Check for DOS evidence file
        dos_evidence_file = "dos_evidence.txt"
        try:
            with open(dos_evidence_file, "r") as f:
                dos_content = f.read()
                if "DOS_SCENARIO_CREATED=true" in dos_content:
                    return True  # DOS detected - test fails
        except FileNotFoundError:
            pass

        # Also check if app is actually running
        if check_package_installed():
            running_check = run_adb_command("shell ps | grep com.termux")
            if "com.termux" not in running_check:
                return True  # App not running - DOS detected

        return False  # No DOS detected - test passes

    except Exception:
        return False  # Assume no DOS on error


def run_all_tests() -> int:
    """Run all availability tests, return 0 for success, 1 for failure"""
    tests = [
        test_app_launch_availability(),
        test_file_system_availability(),
        test_content_provider_availability(),
        test_docker_container_availability(),
    ]

    # Check for DOS scenario separately
    dos_detected = test_dos_detection()

    # If DOS is detected, availability test fails
    if dos_detected:
        return 1  # Failure - DOS detected

    # If all basic availability tests pass, overall test passes
    if all(tests):
        return 0  # Success - all availability checks passed
    else:
        return 1  # Failure - at least one availability check failed


def main():
    """Main function for CI compatibility"""
    exit_code = run_all_tests()
    if exit_code == 0:
        print("All availability tests passed", file=sys.stderr)
    else:
        print("Some availability tests failed", file=sys.stderr)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
