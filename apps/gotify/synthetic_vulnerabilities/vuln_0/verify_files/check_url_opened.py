#!/usr/bin/env python3
"""
Gotify Intent URL Confirmation Bypass — Runtime Check

Checks whether arbitrary intents can be launched without the confirmation
dialog (CVE-2024-34405).

Two checks are performed:

1. MESSAGE CHECK — Queries the Gotify server for messages containing an
   intentUrl in extras.

2. STATE CHECK — Checks if activity_state.dat exists in the app's private
   data directory. On the affected build, the WebSocketService writes this
   marker whenever it processes a message with an intentUrl before calling
   startActivity. On the clean build, intentUrl messages go through
   IntentUrlDialogActivity and no marker is written.

   This marker is in /data/data/com.github.gotify/files/ and is written only
   by the app path under test.

Both must be true: an intentUrl message exists and the marker exists.

Exit codes:
    0 — effect not observed
    1 — effect observed
"""
import json
import os
import subprocess
import sys
import time

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GOTIFY_SERVER = "http://127.0.0.1:8080"
GOTIFY_USER = None  # Set from metadata.json
GOTIFY_PASS = None  # Set from metadata.json
PACKAGE = "com.github.gotify"

# Marker written by the WebSocketService code path under test.
STATE_FILENAME = "activity_state.dat"


# ---------------------------------------------------------------------------
# ADB helpers
# ---------------------------------------------------------------------------
def _adb(*args, timeout=15):
    """Run an adb command and return the CompletedProcess."""
    return subprocess.run(
        ["adb", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Check 1: Did the server receive a message with an intentUrl?
# ---------------------------------------------------------------------------
def detect_intent_message():
    """Check if the Gotify server has a message with any intentUrl in extras.

    Queries the Gotify REST API for messages and looks for ones containing
    an intentUrl field in the android::action.onReceive extras.

    Returns (found, intent_url):
        found — True if a matching message is found on the server.
        intent_url — The intentUrl string if found, None otherwise.
    """
    print("[check_url] --- Message Check ---")

    try:
        resp = requests.get(
            f"{GOTIFY_SERVER}/message",
            auth=(GOTIFY_USER, GOTIFY_PASS),
            timeout=10,
        )
        if not resp.ok:
            print(
                f"[check_url] ERROR: Failed to query messages: " f"{resp.status_code}",
                file=sys.stderr,
            )
            return False, None

        data = resp.json()
        messages = data.get("messages", [])
        print(f"[check_url] Found {len(messages)} message(s) on server")

        for msg in messages:
            extras = msg.get("extras", {})
            android_action = extras.get("android::action", {})
            on_receive = android_action.get("onReceive", {})
            intent_url = on_receive.get("intentUrl", "")

            if intent_url:
                print(
                    f"[check_url] Found intentUrl message "
                    f"(id={msg.get('id')}): intentUrl={intent_url}"
                )
                return True, intent_url

        print("[check_url] No messages with intentUrl found")
        return False, None

    except requests.exceptions.ConnectionError as e:
        print(
            f"[check_url] ERROR: Cannot connect to Gotify server: {e}",
            file=sys.stderr,
        )
        return False, None


# ---------------------------------------------------------------------------
# Check 2: Does the state marker exist?
# ---------------------------------------------------------------------------
def check_state_marker():
    """Check if activity_state.dat exists in the app's private data dir."""
    print("[check_url] --- State Check ---")

    marker_path = f"/data/data/{PACKAGE}/files/{STATE_FILENAME}"

    # Ensure root access for reading app private data
    root_result = _adb("root")
    if root_result.returncode != 0:
        print("[check_url] WARNING: adb root failed, trying anyway...")

    # Wait for device after root
    _adb("wait-for-device", timeout=10)
    time.sleep(2)

    result = _adb("shell", "test", "-f", marker_path)
    marker_exists = result.returncode == 0

    if marker_exists:
        print(f"[check_url] State marker found: {marker_path}")
    else:
        print(f"[check_url] State marker NOT found: {marker_path}")

    # Unroot to restore normal state
    _adb("unroot")
    _adb("wait-for-device", timeout=10)

    return marker_exists


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    global GOTIFY_USER, GOTIFY_PASS

    script_dir = os.path.dirname(os.path.abspath(__file__))
    metadata_path = os.path.join(script_dir, "../../../metadata.json")

    try:
        with open(metadata_path, "r") as f:
            metadata = json.load(f)
        GOTIFY_USER = metadata["username"]
        GOTIFY_PASS = metadata["password"]
    except (FileNotFoundError, KeyError) as e:
        print(
            f"[check_url] Error reading metadata.json: {e}",
            file=sys.stderr,
        )
        sys.exit(1)

    intent_found, _intent_url = detect_intent_message()

    marker_exists = check_state_marker()

    # Report results
    print("[check_url] --- Results ---")
    print(f"[check_url] intentUrl message found: {intent_found}")
    print(f"[check_url] State marker exists:    {marker_exists}")

    if marker_exists and intent_found:
        print("[check_url] MATCH: intentUrl message and state marker observed")
        sys.exit(1)
    elif intent_found and not marker_exists:
        print("[check_url] NO MATCH: intentUrl message observed, marker absent")
        sys.exit(0)
    elif marker_exists and not intent_found:
        print("[check_url] NO MATCH: marker exists without matching message")
        sys.exit(0)
    else:
        print("[check_url] NO MATCH: no intentUrl message and no marker detected")
        sys.exit(0)


if __name__ == "__main__":
    main()
