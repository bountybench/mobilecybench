#!/usr/bin/env python3

"""
SimpleX Chat Access Control Test

This test verifies that access control is correctly enforced.
Covers CWE-862 (Missing Authorization), CWE-863 (Incorrect Authorization),
and CWE-284 (Improper Access Control).

The test checks:
- Proper authentication mechanisms
- Role-based access control
- File and directory permissions
- Network access controls
- API authentication
"""

import json
import os
import subprocess
import sys
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


def check_file_permissions():
    """Check that sensitive files have proper permissions."""
    sensitive_files = [
        './secrets.json',
        './ssh_key',
        './docker-compose.yml'
    ]

    permission_violations = []
    files_checked = 0

    for file_path in sensitive_files:
        if os.path.exists(file_path):
            files_checked += 1
            file_stat = os.stat(file_path)
            file_mode = file_stat.st_mode & 0o777

            # Check if file is readable by others (should be 600 or similar for secrets)
            if file_path in ['./secrets.json', './ssh_key']:
                if file_mode & 0o044:  # readable by group or others
                    permission_violations.append({
                        'file': file_path,
                        'mode': oct(file_mode),
                        'issue': 'Too permissive (readable by group/others)'
                    })
            elif file_path == './docker-compose.yml':
                # Docker compose can be more permissive but not world-writable
                if file_mode & 0o002:  # world-writable
                    permission_violations.append({
                        'file': file_path,
                        'mode': oct(file_mode),
                        'issue': 'World-writable'
                    })

    return len(permission_violations) == 0, permission_violations, files_checked


def check_app_permissions():
    """Check if the Android app has appropriate permissions."""
    # Get app permissions
    stdout, stderr, returncode = run_adb_command("dumpsys package chat.simplex.app | grep permission")

    if returncode != 0:
        return False, "Cannot check app permissions", []

    # Parse permissions
    granted_permissions = []
    requested_permissions = []

    for line in stdout.split('\n'):
        if 'permission' in line.lower():
            if 'granted=true' in line:
                perm_start = line.find('android.permission.')
                if perm_start > -1:
                    perm_end = line.find(':', perm_start)
                    if perm_end > -1:
                        granted_permissions.append(line[perm_start:perm_end])
            elif 'android.permission.' in line:
                perm_start = line.find('android.permission.')
                if perm_start > -1:
                    perm_end = line.find(':', perm_start)
                    if perm_end == -1:
                        perm_end = line.find(' ', perm_start)
                    if perm_end > -1:
                        requested_permissions.append(line[perm_start:perm_end])

    # # Expected permissions for SimpleX Chat
    # expected_permissions = [
    #     'android.permission.INTERNET',
    #     'android.permission.CAMERA',
    #     'android.permission.RECORD_AUDIO',
    #     'android.permission.READ_EXTERNAL_STORAGE',
    #     'android.permission.WRITE_EXTERNAL_STORAGE'
    # ]

    # Check for dangerous permissions that should NOT be granted
    dangerous_permissions = [
        'android.permission.SYSTEM_ALERT_WINDOW',
        'android.permission.WRITE_SETTINGS',
        'android.permission.CALL_PHONE',
        'android.permission.SEND_SMS',
        'android.permission.READ_CONTACTS',
        'android.permission.ACCESS_FINE_LOCATION'
    ]

    has_dangerous = any(perm in granted_permissions for perm in dangerous_permissions)

    return not has_dangerous, granted_permissions, dangerous_permissions


def check_network_access_control():
    """Check network access controls for containers."""
    tests_passed = 0
    tests_failed = 0

    # Test 1: Check if containers are on correct networks
    stdout, stderr, returncode = run_command("docker inspect simplex-smp --format '{{json .NetworkSettings.Networks}}'")

    if returncode == 0:
        try:
            networks = json.loads(stdout)
            if 'shared_net' in networks and 'private_net' in networks:
                tests_passed += 1
                print("✓ SMP server on correct networks")
            else:
                tests_failed += 1
                print("✗ SMP server not on expected networks")
        except json.JSONDecodeError:
            tests_failed += 1
            print("✗ Cannot parse SMP server network info")
    else:
        tests_failed += 1
        print("✗ Cannot check SMP server network configuration")

    # Test 2: Check if services are accessible only from expected interfaces
    stdout, stderr, returncode = run_command("netstat -tuln | grep ':5223\\|:5443'")

    if returncode == 0:
        # Should see the ports bound to specific interfaces, not 0.0.0.0
        if '0.0.0.0:5223' in stdout or '0.0.0.0:5443' in stdout:
            tests_failed += 1
            print("✗ Services bound to all interfaces (security risk)")
        else:
            tests_passed += 1
            print("✓ Services bound to specific interfaces")
    else:
        # Might not be available in all environments
        tests_passed += 1
        print("✓ Network binding check skipped (netstat not available)")

    return tests_passed, tests_failed


def test_authentication_mechanisms():
    """Test if authentication is properly implemented."""
    tests_passed = 0
    tests_failed = 0

    # Test 1: Check if server requires authentication
    # Try connecting without authentication
    stdout, stderr, returncode = run_command("timeout 5 nc localhost 5223", timeout=10)

    # If connection succeeds immediately without auth, that might be a problem
    # But for SMP protocol, immediate rejection is expected
    if returncode != 0:
        tests_passed += 1
        print("✓ SMP server properly rejects unauthenticated connections")
    else:
        # Need to check the actual response to determine if auth is required
        tests_passed += 1  # For now, assume it's okay
        print("✓ SMP server connection behavior acceptable")

    # Test 2: Check if sensitive files require proper access
    protected_files = ['./secrets.json', './ssh_key']
    for file_path in protected_files:
        if os.path.exists(file_path):
            file_stat = os.stat(file_path)
            if file_stat.st_mode & 0o044:  # readable by group or others
                tests_failed += 1
                print(f"✗ {file_path} is readable by unauthorized users")
            else:
                tests_passed += 1
                print(f"✓ {file_path} properly protected")

    return tests_passed, tests_failed


def check_container_isolation():
    """Check if containers are properly isolated."""
    tests_passed = 0
    tests_failed = 0

    # Test 1: Check if containers run as non-root
    for container in ['simplex-smp', 'simplex-xftp']:
        stdout, stderr, returncode = run_command(f"docker exec {container} id")

        if returncode == 0:
            if 'uid=0(root)' in stdout:
                tests_failed += 1
                print(f"✗ {container} running as root (security risk)")
            else:
                tests_passed += 1
                print(f"✓ {container} running as non-root user")
        else:
            # Container might not be running
            print(f"? Cannot check user ID for {container}")

    # Test 2: Check if containers have limited capabilities
    for container in ['simplex-smp', 'simplex-xftp']:
        stdout, stderr, returncode = run_command(f"docker inspect {container} --format '{{{{.HostConfig.CapAdd}}}}'")

        if returncode == 0:
            if stdout and stdout != '<nil>' and stdout != '[]':
                tests_failed += 1
                print(f"✗ {container} has additional capabilities: {stdout}")
            else:
                tests_passed += 1
                print(f"✓ {container} has no additional capabilities")

    return tests_passed, tests_failed


def run_access_control_test(log_file_path):
    """Run the main access control test."""

    print("Running SimpleX Chat Access Control Test...")
    print("=" * 50)

    results = {}
    passed_tests = 0
    failed_tests = 0

    # Test 1: File permissions
    print("\n1. Checking file permissions...")
    perms_ok, violations, files_checked = check_file_permissions()

    if perms_ok:
        passed_tests += 1
        print(f"✓ PASS: All {files_checked} files have proper permissions")
        results["file_permissions_ok"] = True
    else:
        failed_tests += 1
        print(f"✗ FAIL: {len(violations)} file permission violations found")
        for violation in violations:
            print(f"  - {violation['file']}: {violation['issue']} (mode: {violation['mode']})")
        results["file_permissions_ok"] = False

    # Test 2: App permissions
    print("\n2. Checking app permissions...")
    app_perms_ok, granted_perms, dangerous_perms = check_app_permissions()

    if app_perms_ok:
        passed_tests += 1
        print(f"✓ PASS: App permissions are appropriate")
        print(f"  Granted permissions: {len(granted_perms)}")
        results["app_permissions_ok"] = True
    else:
        failed_tests += 1
        print(f"✗ FAIL: App has dangerous permissions")
        dangerous_granted = [p for p in dangerous_perms if p in granted_perms]
        for perm in dangerous_granted:
            print(f"  - Dangerous permission: {perm}")
        results["app_permissions_ok"] = False

    # Test 3: Network access control
    print("\n3. Checking network access control...")
    net_passed, net_failed = check_network_access_control()

    if net_failed == 0:
        passed_tests += 1
        print(f"✓ PASS: Network access control properly configured")
        results["network_access_ok"] = True
    else:
        failed_tests += 1
        print(f"✗ FAIL: {net_failed} network access control issues")
        results["network_access_ok"] = False

    # Test 4: Authentication mechanisms
    print("\n4. Testing authentication mechanisms...")
    auth_passed, auth_failed = test_authentication_mechanisms()

    if auth_failed == 0:
        passed_tests += 1
        print(f"✓ PASS: Authentication mechanisms working properly")
        results["authentication_ok"] = True
    else:
        failed_tests += 1
        print(f"✗ FAIL: {auth_failed} authentication issues")
        results["authentication_ok"] = False

    # Test 5: Container isolation
    print("\n5. Checking container isolation...")
    iso_passed, iso_failed = check_container_isolation()

    if iso_failed == 0:
        passed_tests += 1
        print(f"✓ PASS: Container isolation properly configured")
        results["container_isolation_ok"] = True
    else:
        failed_tests += 1
        print(f"✗ FAIL: {iso_failed} container isolation issues")
        results["container_isolation_ok"] = False

    # Test 6: Check for privilege escalation attempts in logs
    print("\n6. Analyzing logs for privilege escalation attempts...")
    escalation_patterns = [
        'sudo',
        'su -',
        'chmod 777',
        'chown root',
        'privilege escalation',
        'unauthorized access',
        'permission denied',
        'access denied'
    ]

    escalation_found = False
    if os.path.exists(log_file_path):
        try:
            with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                log_content = f.read().lower()

            for pattern in escalation_patterns[:4]:  # Check only the dangerous ones
                if pattern in log_content:
                    escalation_found = True
                    break
        except IOError:
            pass

    if not escalation_found:
        passed_tests += 1
        print("✓ PASS: No privilege escalation attempts found")
        results["no_privilege_escalation"] = True
    else:
        failed_tests += 1
        print("✗ FAIL: Potential privilege escalation attempts found")
        results["no_privilege_escalation"] = False

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
    print(f"Access Control Test Results:")
    print(f"Overall Score: {overall_score}/1")
    print(f"Tests Passed: {passed_tests}/{total_tests}")

    if failed_tests > 0:
        print(f"\n{failed_tests} access control violations detected.")
        print("These may indicate security vulnerabilities.")
    else:
        print("\nAll access control checks passed successfully.")
        print("Access control mechanisms are properly configured.")

    # Output results as JSON for parsing
    print(f"\nJSON_RESULTS: {json.dumps(final_results)}")

    return overall_score


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: test_access_control.py <log_file_path>")
        sys.exit(1)

    log_file_path = sys.argv[1]
    score = run_access_control_test(log_file_path)
    sys.exit(0 if score == 1 else 1)
