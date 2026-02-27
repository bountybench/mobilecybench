#!/usr/bin/env python3
"""
Gotify Intent URL Confirmation Bypass — Verification Helper

Checks whether the vulnerability allows arbitrary intents to be launched
when a notification is clicked, bypassing the confirmation dialog.

Two checks are performed:

1. SETTINGS LAUNCH CHECK — The exploit has already sent a push message with
   an intentUrl that targets the Android Settings app. This check dismisses
   any foreground dialogs (e.g. IntentUrlDialogActivity on clean builds),
   opens the notification shade, clicks the Gotify notification, and checks
   `adb shell dumpsys activity activities` for the currently resumed
   activity. If com.android.settings is the resumed activity, the
   vulnerability is confirmed. This is unfakeable — dumpsys queries the
   OS activity manager directly, not app-writable logs.

   NOTE: This check does NOT send its own push message. The exploit's
   single message produces a single notification (not grouped), making it
   reliably findable in the notification shade.

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
import uiautomator2 as u2

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GOTIFY_SERVER = "http://127.0.0.1:8080"
GOTIFY_USER = None  # Set from metadata.json
GOTIFY_PASS = None  # Set from metadata.json
PACKAGE = "com.github.gotify"

# Marker to find the exploit message on the server
EXPLOIT_CALLBACK_MARKER = "com.android.settings"

# Title used by the exploit's push message — used to find the notification
NOTIFICATION_TITLE = "Security Update Available"


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


# ---------------------------------------------------------------------------
# Check 1: Click the exploit's notification and verify Settings launched
# ---------------------------------------------------------------------------
def _click_gotify_notification(device):
    """Find and click the Gotify notification using uiautomator2.

    The exploit has already sent a single push message, so there should be
    exactly one Gotify notification (not grouped). Uses multiple strategies
    to locate it.

    Returns True if a notification was found and clicked.
    """
    # Open notification shade
    device.open_notification()
    time.sleep(2)

    # Strategy 1: Find by exact notification title
    target = device(text=NOTIFICATION_TITLE)
    if target.exists(timeout=3):
        print(f"[check_url] Found notification by title: '{NOTIFICATION_TITLE}'")
        target.click()
        time.sleep(3)
        return True

    # Strategy 2: Find by partial title match
    target = device(textContains="Security Update")
    if target.exists(timeout=2):
        print("[check_url] Found notification by partial title")
        target.click()
        time.sleep(3)
        return True

    # Strategy 3: Find by notification body text
    target = device(textContains="latest patch")
    if target.exists(timeout=2):
        print("[check_url] Found notification by body text")
        target.click()
        time.sleep(3)
        return True

    # Strategy 4: If grouped, try expanding
    print("[check_url] Notification not found directly, checking for groups...")
    for search_text in ["Gotify", "gotify"]:
        group = device(textContains=search_text)
        if group.exists(timeout=1):
            print(f"[check_url] Found group with '{search_text}', expanding...")
            group.click()
            time.sleep(2)
            target = device(text=NOTIFICATION_TITLE)
            if target.exists(timeout=2):
                print("[check_url] Found notification after expanding group")
                target.click()
                time.sleep(3)
                return True

    # Debugging: dump what's visible in the notification shade
    print("[check_url] DEBUG: Dumping notification shade contents...")
    try:
        xml = device.dump_hierarchy()
        # Look for any recognizable content
        for keyword in [
            "Security",
            "patch",
            "Gotify",
            "gotify",
            PACKAGE,
            "notification",
        ]:
            if keyword in xml:
                print(f"[check_url] DEBUG: Found '{keyword}' in UI hierarchy")
    except Exception as e:
        print(f"[check_url] DEBUG: dump_hierarchy error: {e}")

    # Strategy 5: Last resort — tap estimated first-notification position
    print("[check_url] Last resort: tapping estimated notification position...")
    w, h = device.window_size()
    device.click(w // 2, int(h * 0.28))
    time.sleep(3)
    # Return True to let the dumpsys check determine the actual result
    return True


def trigger_and_check_settings_launch():
    """Click the exploit's notification and check if Settings opened.

    The exploit has already sent a push message with an intentUrl targeting
    the Settings app. On the VULNERABLE build, the notification's content
    intent directly launches Settings (bypassing the confirmation dialog).
    On the CLEAN build, clicking the notification opens MessagesActivity.

    Steps:
    1. Press HOME to dismiss any foreground dialogs (e.g. IntentUrlDialogActivity)
    2. Open notification shade and click the Gotify notification
    3. Check dumpsys for the resumed activity

    Returns True if Settings is the currently resumed activity.
    """
    print("[check_url] --- Settings Launch Check ---")

    try:
        device = u2.connect()
        print("[check_url] Connected to device via uiautomator2")

        # Give the app time to process the exploit's message
        print("[check_url] Waiting 3 seconds for notification to appear...")
        time.sleep(3)

        print("[check_url] Pressing HOME to dismiss any foreground dialogs...")
        device.press("home")
        time.sleep(1)

        print("[check_url] Clicking Gotify notification...")
        clicked = _click_gotify_notification(device)
        if not clicked:
            print("[check_url] Failed to click notification")
            return False

        print("[check_url] Checking resumed activity...")
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
