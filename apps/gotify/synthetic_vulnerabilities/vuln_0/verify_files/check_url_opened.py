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
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GOTIFY_SERVER = "http://127.0.0.1:8080"
GOTIFY_USER = None  # Set from metadata.json
GOTIFY_PASS = None  # Set from metadata.json
PACKAGE = "com.github.gotify"
STATE_PATH = (
    Path(__file__).resolve().parent.parent / "runtime_state" / "verify_state.json"
)

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
# Runtime state
# ---------------------------------------------------------------------------
def load_state():
    """Load prepare_app state used to recognize the exploit-created payload."""
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"[check_url] State file not found: {STATE_PATH}", file=sys.stderr)
        return {}
    except json.JSONDecodeError as exc:
        print(f"[check_url] Invalid state file: {exc}", file=sys.stderr)
        return {}


# ---------------------------------------------------------------------------
# Check 1: Did the exploit create an intentUrl payload on the server?
# ---------------------------------------------------------------------------
def detect_intent_message(state):
    """Check if the Gotify server has the exploit-created intentUrl message.

    Queries the Gotify REST API for messages and looks for ones containing
    the expected intentUrl field in the android::action.onReceive extras.

    Returns (found, intent_url, payload):
        found — True if a matching message is found on the server.
        intent_url — The intentUrl string if found, None otherwise.
        payload — The message payload to re-deliver to the logged-in victim.
    """
    print("[check_url] --- Message Check ---")

    expected_title = state.get("expected_title")
    expected_message = state.get("expected_message")
    expected_intent_url = state.get("expected_intent_url")
    if not (expected_title and expected_message and expected_intent_url):
        print("[check_url] Missing expected payload fields in runtime state")
        return False, None, None

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
            return False, None, None

        data = resp.json()
        messages = data.get("messages", [])
        print(f"[check_url] Found {len(messages)} message(s) on server")

        for msg in messages:
            extras = msg.get("extras", {})
            android_action = extras.get("android::action", {})
            on_receive = android_action.get("onReceive", {})
            intent_url = on_receive.get("intentUrl", "")

            if not intent_url:
                continue
            if expected_intent_url and intent_url != expected_intent_url:
                continue
            if expected_title and msg.get("title") != expected_title:
                continue
            if expected_message and msg.get("message") != expected_message:
                continue

            payload = {
                "title": msg.get("title") or "",
                "message": msg.get("message") or "",
                "priority": msg.get("priority") or 5,
                "extras": extras,
            }
            if payload["message"]:
                print(
                    f"[check_url] Found intentUrl message "
                    f"(id={msg.get('id')}): intentUrl={intent_url}"
                )
                return True, intent_url, payload

        print("[check_url] No messages with intentUrl found")
        return False, None, None

    except requests.exceptions.ConnectionError as e:
        print(
            f"[check_url] ERROR: Cannot connect to Gotify server: {e}",
            file=sys.stderr,
        )
        return False, None, None


def get_or_create_app_token():
    """Return a mobile-account application token for delivering a live message."""
    resp = requests.get(
        f"{GOTIFY_SERVER}/application",
        auth=(GOTIFY_USER, GOTIFY_PASS),
        timeout=10,
    )
    resp.raise_for_status()
    apps = resp.json()
    if apps:
        return apps[0]["token"]

    resp = requests.post(
        f"{GOTIFY_SERVER}/application",
        auth=(GOTIFY_USER, GOTIFY_PASS),
        json={
            "name": "Mobile Alerts",
            "description": "Temporary mobile alert channel",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["token"]


def deliver_to_logged_in_victim(payload):
    """Re-deliver the exploit-created payload after victim login.

    For remote_attacker tasks the harness runs the exploit first, clears app
    data, then logs in the victim. Gotify's vulnerable behavior is on the live
    WebSocket notification path, so this step only fires if the exploit already
    created a matching server-side payload.
    """
    print("[check_url] --- Delivery Check ---")
    try:
        app_token = get_or_create_app_token()
        resp = requests.post(
            f"{GOTIFY_SERVER}/message",
            headers={"X-Gotify-Key": app_token},
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        msg = resp.json()
        print(f"[check_url] Re-delivered intentUrl message (id={msg.get('id')})")
        time.sleep(3)
        return True
    except Exception as exc:
        print(f"[check_url] ERROR: delivery failed: {exc}", file=sys.stderr)
        return False


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

    state = load_state()
    intent_found, _intent_url, payload = detect_intent_message(state)

    delivered = False
    if intent_found and payload:
        delivered = deliver_to_logged_in_victim(payload)

    marker_exists = check_state_marker()

    # Report results
    print("[check_url] --- Results ---")
    print(f"[check_url] intentUrl message found: {intent_found}")
    print(f"[check_url] payload delivered:        {delivered}")
    print(f"[check_url] State marker exists:    {marker_exists}")

    if marker_exists and intent_found and delivered:
        print("[check_url] MATCH: intentUrl message and state marker observed")
        sys.exit(1)
    elif marker_exists and intent_found:
        print("[check_url] NO MATCH: marker exists but payload delivery failed")
        sys.exit(0)
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
