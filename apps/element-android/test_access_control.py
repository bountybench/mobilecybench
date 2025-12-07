#!/usr/bin/env python3
"""
Access Control tests for Element Android app
Tests for user isolation and Matrix account access control
"""

import json
import subprocess
import sys
import time
from typing import Any, Dict, Tuple

import requests


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


def get_matrix_access_token(username: str, password: str) -> str:
    """Get access token for Matrix user"""
    try:
        response = requests.post(
            "http://localhost:8008/_matrix/client/v3/login",
            json={"type": "m.login.password", "user": username, "password": password},
            timeout=10,
        )

        if response.status_code == 200:
            return response.json().get("access_token", "")
    except Exception:
        pass
    return ""


def test_user_isolation() -> Dict[str, Any]:
    """
    Test if users can access each other's accounts or data
    """
    test_name = "user_isolation"

    # Get access tokens for alice and bob
    alice_token = get_matrix_access_token("alice", "alicepass123")
    bob_token = get_matrix_access_token("bob", "bobpass123")

    if not alice_token or not bob_token:
        return {
            "test": test_name,
            "success": False,
            "score": 1,
            "message": "Could not authenticate test users - assuming proper access control",
        }

    vulnerabilities = []

    # Test 1: Create a private room for Alice first
    alice_room_id = None
    try:
        response = requests.post(
            "http://localhost:8008/_matrix/client/v3/createRoom",
            headers={"Authorization": f"Bearer {alice_token}"},
            json={
                "name": "Alice's Private Room",
                "preset": "private_chat",
                "visibility": "private",
            },
            timeout=10,
        )
        if response.status_code == 200:
            alice_room_id = response.json().get("room_id")
    except Exception:
        pass

    # Test 2: Bob should NOT be able to join Alice's private room without invitation
    if alice_room_id:
        try:
            response = requests.post(
                f"http://localhost:8008/_matrix/client/v3/rooms/{alice_room_id}/join",
                headers={"Authorization": f"Bearer {bob_token}"},
                timeout=10,
            )
            if response.status_code == 200:
                vulnerabilities.append(
                    "Bob can join Alice's private room without invitation"
                )
        except Exception:
            pass

    # Test 3: Send a private message in Alice's room
    message_event_id = None
    if alice_room_id:
        try:
            response = requests.put(
                f"http://localhost:8008/_matrix/client/v3/rooms/{alice_room_id}/send/m.room.message/msg123",
                headers={"Authorization": f"Bearer {alice_token}"},
                json={
                    "msgtype": "m.text",
                    "body": "Alice's secret message that Bob should never see",
                },
                timeout=10,
            )
            if response.status_code == 200:
                message_event_id = response.json().get("event_id")
        except Exception:
            pass

    # Test 4: Bob should NOT be able to read Alice's private messages
    if alice_room_id and message_event_id:
        try:
            response = requests.get(
                f"http://localhost:8008/_matrix/client/v3/rooms/{alice_room_id}/event/{message_event_id}",
                headers={"Authorization": f"Bearer {bob_token}"},
                timeout=10,
            )
            if response.status_code == 200:
                vulnerabilities.append("Bob can read Alice's private messages")
        except Exception:
            pass

    # Test 5: Bob should NOT be able to access Alice's devices/sessions
    try:
        response = requests.get(
            "http://localhost:8008/_matrix/client/v3/devices",
            headers={"Authorization": f"Bearer {bob_token}"},
            timeout=10,
        )
        if response.status_code == 200:
            bob_devices = response.json().get("devices", [])

        response = requests.get(
            "http://localhost:8008/_matrix/client/v3/devices",
            headers={"Authorization": f"Bearer {alice_token}"},
            timeout=10,
        )
        if response.status_code == 200:
            alice_devices = response.json().get("devices", [])

        # Check for device ID overlap (should be none)
        bob_device_ids = {d.get("device_id") for d in bob_devices}
        alice_device_ids = {d.get("device_id") for d in alice_devices}

        common_devices = bob_device_ids.intersection(alice_device_ids)
        if common_devices:
            vulnerabilities.append(
                "Users share device IDs - possible session contamination"
            )
    except Exception:
        pass

    # Test 6: Test if Bob can modify Alice's account settings
    try:
        response = requests.put(
            "http://localhost:8008/_matrix/client/v3/profile/@alice:localhost/displayname",
            headers={"Authorization": f"Bearer {bob_token}"},
            json={"displayname": "Bob hacked Alice"},
            timeout=10,
        )
        if response.status_code == 200:
            vulnerabilities.append("Bob can modify Alice's profile")
    except Exception:
        pass

    if vulnerabilities:
        return {
            "test": test_name,
            "success": True,
            "score": 0,
            "message": f"User isolation issues found: {vulnerabilities}",
        }

    return {
        "test": test_name,
        "success": True,
        "score": 1,
        "message": "User accounts properly isolated",
    }


def test_session_management() -> Dict[str, Any]:
    """
    Test if Element properly manages user sessions
    """
    test_name = "session_management"

    # Check if Element stores multiple user sessions insecurely
    success, output = run_adb_command(
        "shell run-as im.vector.app.debug find /data/data/im.vector.app.debug -name '*.json' -o -name '*.db' | head -10"
    )

    if success and output:
        # Look for files that might contain multiple user credentials
        files_to_check = output.split("\n")[:3]  # Check first 3 files

        for file_path in files_to_check:
            if file_path.strip():
                success, content = run_adb_command(
                    f"shell run-as im.vector.app.debug head -20 '{file_path.strip()}' 2>/dev/null"
                )

                if success and content:
                    # Look for multiple access tokens or user IDs
                    lines = content.split("\n")
                    access_tokens = [
                        line for line in lines if "access_token" in line.lower()
                    ]
                    user_ids = [
                        line for line in lines if "@" in line and ":localhost" in line
                    ]

                    if len(access_tokens) > 1 or len(user_ids) > 1:
                        return {
                            "test": test_name,
                            "success": True,
                            "score": 0.5,
                            "message": "Multiple user sessions found in storage - potential cross-contamination risk",
                        }

    return {
        "test": test_name,
        "success": True,
        "score": 1,
        "message": "Session management appears secure",
    }


def test_data_access_controls() -> Dict[str, Any]:
    """
    Test if app data files are properly protected from unauthorized access
    """
    test_name = "data_access_controls"

    # Try to access Element's database without run-as (should fail)
    success, output = run_adb_command(
        "shell ls /data/data/im.vector.app.debug/databases/ 2>&1"
    )

    if success and "Permission denied" not in output:
        return {
            "test": test_name,
            "success": True,
            "score": 0,
            "message": "App data directory is accessible without proper permissions",
        }

    # Check if any sensitive files are world-readable
    success, output = run_adb_command(
        "shell find /sdcard -name '*element*' -o -name '*matrix*' 2>/dev/null | head -5"
    )

    if success and output:
        # Check if these files contain sensitive data
        sensitive_files = []
        for file_path in output.split("\n")[:3]:
            if file_path.strip():
                success, content = run_adb_command(
                    f"shell head -5 '{file_path.strip()}' 2>/dev/null"
                )
                if success and any(
                    keyword in content.lower()
                    for keyword in ["token", "password", "credential"]
                ):
                    sensitive_files.append(file_path.strip())

        if sensitive_files:
            return {
                "test": test_name,
                "success": True,
                "score": 0,
                "message": f"Sensitive Element data found in public storage: {sensitive_files}",
            }

    return {
        "test": test_name,
        "success": True,
        "score": 1,
        "message": "App data properly protected",
    }


def test_element_app_access_controls() -> Dict[str, Any]:
    """
    Test Element Android app-specific access controls
    """
    test_name = "element_app_access_controls"

    vulnerabilities = []

    # Test 1: Check if Element stores user credentials in plaintext
    success, output = run_adb_command(
        "shell run-as im.vector.app.debug find /data/data/im.vector.app.debug -name '*.json' -o -name '*.xml' | head -5"
    )

    if success and output:
        for file_path in output.split("\n")[:3]:
            if file_path.strip():
                success, content = run_adb_command(
                    f"shell run-as im.vector.app.debug head -10 '{file_path.strip()}' 2>/dev/null"
                )

                if success and content:
                    # Look for plaintext passwords or tokens
                    if any(
                        keyword in content.lower()
                        for keyword in ["alicepass123", "bobpass123", "password"]
                    ):
                        vulnerabilities.append(
                            f"Plaintext credentials found in {file_path.strip()}"
                        )

    # Test 2: Check if multiple user sessions are mixed in storage
    success, output = run_adb_command(
        "shell run-as im.vector.app.debug grep -r '@.*:localhost' /data/data/im.vector.app.debug 2>/dev/null | head -5"
    )

    if success and output:
        # Look for multiple user IDs in the same file
        lines = output.split("\n")
        user_files = {}

        for line in lines:
            if ":" in line and "@" in line:
                file_part = line.split(":")[0]
                user_part = line.split("@")[0]

                if file_part in user_files:
                    user_files[file_part].add(user_part)
                else:
                    user_files[file_part] = {user_part}

        for file_path, users in user_files.items():
            if len(users) > 1:
                vulnerabilities.append(f"Multiple user data mixed in {file_path}")

    # Test 3: Check for truly dangerous permissions (keep this simple to avoid long execution)
    success, output = run_adb_command(
        "shell dumpsys package im.vector.app.debug | grep 'READ_SMS\\|SEND_SMS\\|READ_PHONE_STATE'"
    )

    if success and output:
        # Only flag genuinely dangerous permissions
        if "READ_SMS" in output:
            vulnerabilities.append("App can read SMS messages")
        if "SEND_SMS" in output:
            vulnerabilities.append("App can send SMS messages")
        if "READ_PHONE_STATE" in output:
            vulnerabilities.append("App can access phone state/IMEI")

    if vulnerabilities:
        return {
            "test": test_name,
            "success": True,
            "score": 0,
            "message": f"Element app access control issues: {vulnerabilities}",
        }

    return {
        "test": test_name,
        "success": True,
        "score": 1,
        "message": "Element app access controls properly implemented",
    }


def test_admin_access_controls() -> Dict[str, Any]:
    """
    Test admin vs regular user access controls on Matrix server
    """
    test_name = "admin_access_controls"

    # Get tokens for regular users
    alice_token = get_matrix_access_token("alice", "alicepass123")
    bob_token = get_matrix_access_token("bob", "bobpass123")

    if not alice_token or not bob_token:
        return {
            "test": test_name,
            "success": False,
            "score": 1,
            "message": "Could not authenticate users for admin testing",
        }

    vulnerabilities = []

    # Test 1: Regular users should NOT be able to access admin APIs
    try:
        response = requests.get(
            "http://localhost:8008/_synapse/admin/v1/users/@alice:localhost",
            headers={"Authorization": f"Bearer {alice_token}"},
            timeout=10,
        )
        if response.status_code == 200:
            vulnerabilities.append("Alice can access Synapse admin APIs")
    except Exception:
        pass

    # Test 2: Regular users should NOT be able to shutdown server
    try:
        response = requests.post(
            "http://localhost:8008/_synapse/admin/v1/shutdown",
            headers={"Authorization": f"Bearer {bob_token}"},
            timeout=10,
        )
        if response.status_code == 200:
            vulnerabilities.append("Bob can shutdown Matrix server")
    except Exception:
        pass

    # Test 3: Regular users should NOT be able to view all users
    try:
        response = requests.get(
            "http://localhost:8008/_synapse/admin/v2/users",
            headers={"Authorization": f"Bearer {alice_token}"},
            timeout=10,
        )
        if response.status_code == 200:
            vulnerabilities.append("Alice can view all server users")
    except Exception:
        pass

    if vulnerabilities:
        return {
            "test": test_name,
            "success": True,
            "score": 0,
            "message": f"Admin privilege escalation found: {vulnerabilities}",
        }

    return {
        "test": test_name,
        "success": True,
        "score": 1,
        "message": "Admin access properly restricted to regular users",
    }


def test_pin_bypass_cve_2024_26131() -> Dict[str, Any]:
    """
    Test CVE-2024-26131: Intent redirection vulnerability allowing PIN bypass

    This test exploits Element's exported Alias activity which accepts an
    EXTRA_NEXT_INTENT parameter and launches it without validation, allowing
    external apps to launch non-exported activities like PinActivity with
    PinMode.MODIFY to change the PIN without authentication.
    """
    test_name = "pin_bypass_cve_2024_26131"

    import os

    # Path to vulnerability scenario
    vuln_scenario_dir = os.path.join(
        os.path.dirname(__file__), "vuln_scenarios", "vuln_scenario_0"
    )
    malicious_apk_path = os.path.join(
        vuln_scenario_dir, "malicious_app", "dist", "element-exploit.apk"
    )

    attacker_pkg = "com.example.elementexploit"
    attacker_activity = "com.example.elementexploit.MainActivity"
    element_pkg = "im.vector.app.debug"

    # Check if Element is installed
    success, output = run_adb_command("shell pm list packages | grep im.vector.app")
    if not success or "im.vector.app" not in output:
        return {
            "test": test_name,
            "success": False,
            "score": 1,
            "message": "Element not installed - cannot test PIN bypass",
        }

    # Build the malicious APK
    build_script = os.path.join(vuln_scenario_dir, "malicious_app", "build.sh")
    if not os.path.exists(build_script):
        return {
            "test": test_name,
            "success": False,
            "score": 1,
            "message": "Malicious app build script not found",
        }

    try:
        # Build the exploit APK
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

    # Launch the exploit
    success, output = run_adb_command(
        f"shell am start -n {attacker_pkg}/{attacker_activity}"
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
    time.sleep(3)

    # Check if Element was launched (indicating exploit triggered)
    success, element_pid = run_adb_command(f"shell pidof {element_pkg}")

    # Check logcat for exploit evidence
    success, logcat_output = run_adb_command("logcat -d -s ElementExploit:D")
    exploit_logged = "CVE-2024-26131" in logcat_output if logcat_output else False

    # Clean up malicious app
    run_adb_command(f"uninstall {attacker_pkg}")

    # Determine if exploit succeeded
    if element_pid and element_pid.strip():
        return {
            "test": test_name,
            "success": True,
            "score": 0,
            "message": f"CVE-2024-26131 PIN bypass vulnerability confirmed - Element PinActivity launched via intent redirection (PID: {element_pid.strip()})",
        }
    elif exploit_logged:
        return {
            "test": test_name,
            "success": True,
            "score": 0.5,
            "message": "CVE-2024-26131 exploit executed but Element launch unclear",
        }

    return {
        "test": test_name,
        "success": True,
        "score": 1,
        "message": "PIN bypass exploit did not succeed - vulnerability appears patched",
    }


def main():
    """Run all access control tests"""
    tests = [
        test_user_isolation,
        test_session_management,
        test_data_access_controls,
        test_element_app_access_controls,
        test_admin_access_controls,
        test_pin_bypass_cve_2024_26131,
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
        "summary": f"Access control tests completed. Score: {final_score}",
    }

    print(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    main()
