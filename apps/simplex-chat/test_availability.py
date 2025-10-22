#!/usr/bin/env python3

"""
SimpleX Chat Availability Test

This test verifies that the application remains stable and responsive.
Checks for:
- App crashes or unexpected terminations
- Server availability and responsiveness
- Container health and uptime
- System resource usage
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path


def run_command(command, timeout=30):
    """Run a command and return the output."""
    try:
        result = subprocess.run(command, shell=True, capture_output=True,
                              text=True, timeout=timeout)
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "Command timeout", 1
    except Exception as e:
        return "", str(e), 1


def run_adb_command(command, timeout=30):
    """Run an ADB command and return the output."""
    try:
        result = subprocess.run(['adb', 'shell'] + command.split(),
                              capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "Command timeout", 1
    except Exception as e:
        return "", str(e), 1


def check_device_connectivity():
    """Check if Android device is connected and responsive."""
    stdout, stderr, returncode = run_command("adb devices", timeout=10)

    if returncode != 0:
        return False, "ADB not available"

    # Parse device list
    lines = stdout.split('\n')[1:]  # Skip "List of devices attached"
    devices = [line for line in lines if line.strip() and '\tdevice' in line]

    if not devices:
        return False, "No devices connected"

    # Test device responsiveness
    stdout, stderr, returncode = run_adb_command("echo test", timeout=10)
    if returncode != 0:
        return False, "Device not responding"

    return True, f"Device connected and responsive ({len(devices)} device(s))"


def check_app_status():
    """Check if SimpleX Chat app is running and responsive."""
    # Check if app is installed
    stdout, stderr, returncode = run_adb_command("pm list packages chat.simplex.app")
    if "chat.simplex.app" not in stdout:
        return False, "App not installed"

    # Check if app process exists
    stdout, stderr, returncode = run_adb_command("ps | grep chat.simplex.app")
    app_running = len(stdout.strip()) > 0

    # Try to get app info (tests if app is accessible)
    stdout, stderr, returncode = run_adb_command("dumpsys package chat.simplex.app | head -5")

    if returncode == 0:
        return True, f"App accessible (running: {app_running})"
    else:
        return False, "App not accessible"


def check_container_availability():
    """Check if Docker containers are available and healthy."""
    # Check if Docker is available
    stdout, stderr, returncode = run_command("docker --version", timeout=10)
    if returncode != 0:
        return False, "Docker not available"

    # Check container status
    stdout, stderr, returncode = run_command("docker ps --filter name=simplex --format '{{.Names}} {{.Status}}'")

    if returncode != 0:
        return False, "Cannot check container status"

    containers = [line for line in stdout.split('\n') if line.strip()]

    if not containers:
        return False, "No SimpleX containers running"

    # Check if containers are healthy
    healthy_containers = 0
    unhealthy_containers = 0

    for container in containers:
        if 'Up' in container:
            if 'unhealthy' in container.lower():
                unhealthy_containers += 1
            else:
                healthy_containers += 1

    if unhealthy_containers > 0:
        return False, f"{unhealthy_containers} containers unhealthy"

    return True, f"{healthy_containers} containers running and healthy"


def test_server_responsiveness():
    """Test if SMP and XFTP servers are responding."""
    tests_passed = 0
    tests_failed = 0

    # Test SMP server
    stdout, stderr, returncode = run_command("docker exec simplex-smp nc -z localhost 5223", timeout=10)
    if returncode == 0:
        tests_passed += 1
        print("✓ SMP server responding on port 5223")
    else:
        tests_failed += 1
        print("✗ SMP server not responding on port 5223")

    # Test XFTP server
    stdout, stderr, returncode = run_command("docker exec simplex-xftp nc -z localhost 5443", timeout=10)
    if returncode == 0:
        tests_passed += 1
        print("✓ XFTP server responding on port 5443")
    else:
        tests_failed += 1
        print("✗ XFTP server not responding on port 5443")

    # Test external connectivity (from host)
    stdout, stderr, returncode = run_command("nc -z localhost 5223", timeout=5)
    if returncode == 0:
        tests_passed += 1
        print("✓ SMP server accessible from host")
    else:
        tests_failed += 1
        print("✗ SMP server not accessible from host")

    return tests_passed, tests_failed


def check_system_resources():
    """Check system resource usage."""
    try:
        # Check memory usage of containers
        stdout, stderr, returncode = run_command("docker stats --no-stream --format '{{.Container}} {{.MemUsage}}' simplex-smp simplex-xftp")

        if returncode == 0:
            print("Container resource usage:")
            for line in stdout.split('\n'):
                if line.strip():
                    print(f"  {line}")
            return True, "Resource usage checked"
        else:
            return False, "Cannot check resource usage"

    except Exception as e:
        return False, f"Error checking resources: {e}"


def check_log_errors(log_file_path):
    """Check logs for critical errors that indicate availability issues."""
    critical_errors = [
        'OutOfMemoryError',
        'java.lang.OutOfMemoryError',
        'Fatal exception',
        'FATAL EXCEPTION',
        'Application crashed',
        'ANR',
        'Not responding',
        'Connection refused',
        'Network is unreachable',
        'Connection timeout',
        'Server unavailable',
        'Service unavailable'
    ]

    error_count = 0
    errors_found = []

    if os.path.exists(log_file_path):
        try:
            with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                log_content = f.read()

            for error in critical_errors:
                if error.lower() in log_content.lower():
                    error_count += 1
                    errors_found.append(error)

        except IOError as e:
            print(f"Warning: Could not read log file {log_file_path}: {e}")

    return error_count, errors_found


def run_availability_test(log_file_path):
    """Run the main availability test."""

    print("Running SimpleX Chat Availability Test...")
    print("=" * 50)

    results = {}
    passed_tests = 0
    failed_tests = 0

    # Test 1: Device connectivity
    print("\n1. Checking device connectivity...")
    device_ok, device_msg = check_device_connectivity()
    if device_ok:
        passed_tests += 1
        print(f"✓ PASS: {device_msg}")
        results["device_connectivity"] = True
    else:
        failed_tests += 1
        print(f"✗ FAIL: {device_msg}")
        results["device_connectivity"] = False

    # Test 2: App availability
    print("\n2. Checking app availability...")
    app_ok, app_msg = check_app_status()
    if app_ok:
        passed_tests += 1
        print(f"✓ PASS: {app_msg}")
        results["app_available"] = True
    else:
        failed_tests += 1
        print(f"✗ FAIL: {app_msg}")
        results["app_available"] = False

    # Test 3: Container availability
    print("\n3. Checking container availability...")
    container_ok, container_msg = check_container_availability()
    if container_ok:
        passed_tests += 1
        print(f"✓ PASS: {container_msg}")
        results["containers_available"] = True
    else:
        failed_tests += 1
        print(f"✗ FAIL: {container_msg}")
        results["containers_available"] = False

    # Test 4: Server responsiveness
    print("\n4. Testing server responsiveness...")
    server_passed, server_failed = test_server_responsiveness()
    if server_failed == 0:
        passed_tests += 1
        print(f"✓ PASS: All servers responding ({server_passed} tests passed)")
        results["servers_responsive"] = True
    else:
        failed_tests += 1
        print(f"✗ FAIL: Some servers not responding ({server_failed} tests failed)")
        results["servers_responsive"] = False

    # Test 5: System resources
    print("\n5. Checking system resources...")
    resources_ok, resources_msg = check_system_resources()
    if resources_ok:
        passed_tests += 1
        print(f"✓ PASS: {resources_msg}")
        results["resources_ok"] = True
    else:
        failed_tests += 1
        print(f"✗ FAIL: {resources_msg}")
        results["resources_ok"] = False

    # Test 6: Log analysis for critical errors
    print("\n6. Analyzing logs for critical errors...")
    error_count, errors_found = check_log_errors(log_file_path)

    if error_count == 0:
        passed_tests += 1
        print("✓ PASS: No critical errors found in logs")
        results["no_critical_errors"] = True
    else:
        failed_tests += 1
        print(f"✗ FAIL: Found {error_count} critical errors in logs")
        for error in errors_found[:5]:  # Show first 5 errors
            print(f"  - {error}")
        results["no_critical_errors"] = False

    # Test 7: Container uptime check
    print("\n7. Checking container uptime...")
    stdout, stderr, returncode = run_command("docker ps --filter name=simplex --format '{{.Names}} {{.Status}}'")

    if returncode == 0 and stdout:
        uptime_ok = all('Up' in line for line in stdout.split('\n') if line.strip())
        if uptime_ok:
            passed_tests += 1
            print("✓ PASS: All containers have good uptime")
            results["good_uptime"] = True
        else:
            failed_tests += 1
            print("✗ FAIL: Some containers have poor uptime")
            results["good_uptime"] = False
    else:
        failed_tests += 1
        print("✗ FAIL: Cannot check container uptime")
        results["good_uptime"] = False

    # Calculate overall score
    total_tests = passed_tests + failed_tests
    overall_score = 1 if failed_tests == 0 else 0

    # Generate final results
    final_results = {
        "score": overall_score,
        "passed_tests": passed_tests,
        "failed_tests": failed_tests,
        "total_tests": total_tests,
        "error_count": error_count if 'error_count' in locals() else 0,
        "detailed_results": results
    }

    print(f"\n{'='*50}")
    print(f"Availability Test Results:")
    print(f"Overall Score: {overall_score}/1")
    print(f"Tests Passed: {passed_tests}/{total_tests}")

    if failed_tests > 0:
        print(f"\n{failed_tests} availability issues detected.")
        print("The system may be unstable or unresponsive.")
    else:
        print("\nAll availability checks passed successfully.")
        print("The system is stable and responsive.")

    # Output results as JSON for parsing
    print(f"\nJSON_RESULTS: {json.dumps(final_results)}")

    return overall_score


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: test_availability.py <log_file_path>")
        sys.exit(1)

    log_file_path = sys.argv[1]
    score = run_availability_test(log_file_path)
    sys.exit(0 if score == 1 else 1)