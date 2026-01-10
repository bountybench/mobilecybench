#!/usr/bin/env python3
"""
Automates Conversations XMPP login using UIAutomator2.
Extremely robust with idempotency - works on first run and subsequent runs.

Complete flow (verified manually):
1. Welcome screen → Click "I already have an account"
2. Login form → Fill username + password → Click Save
3. Certificate dialog → Click "Always"
4. Publish avatar screen → Click "Skip"
5. Contacts permission → Click "Allow"
6. Notifications permission → Click "Allow"
7. Verify logged in by checking for speed_dial, action_search, or "Contacts" text
"""
import argparse
import json
import os
import subprocess
import sys
import time

import uiautomator2 as u2

# Import shared utilities
from ui_automation_utils import (
    TIMEOUT_NORMAL,
    TIMEOUT_SLOW,
    capture_failure_context,
    fill_login_form,
    handle_certificate_dialog,
    handle_publish_avatar_screen,
    log,
    wait_for_ui_stable,
)

SCRIPT_NAME = "login_ui"

# Get script directory for relative paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SECRETS_PATH = os.path.join(SCRIPT_DIR, "../../secrets.json")

# Parse arguments
parser = argparse.ArgumentParser(description="Conversations XMPP login automation")
parser.add_argument(
    "--secrets", default=DEFAULT_SECRETS_PATH, help="Path to secrets.json"
)
parser.add_argument("--username", default="user1@10.0.2.2", help="XMPP username")
parser.add_argument("--user-key", default="user1_password", help="Key in secrets.json")
args = parser.parse_args()

# Load credentials from secrets.json
with open(args.secrets, "r") as f:
    secrets = json.load(f)
    password = secrets[args.user_key]

# Connect to device
d = u2.connect()

PACKAGE = "eu.siacs.conversations"


def check_if_logged_in():
    """
    Check if user is already logged in.
    Logged-in indicators (verified manually):
    - speed_dial resource ID (preferred - stable)
    - action_search resource ID (preferred - stable)
    - "Contacts" text on screen (fallback - language-dependent)
    """
    log("Checking if already logged in...", SCRIPT_NAME)

    # Check UI elements using resource IDs (preferred - stable across languages)
    if d(resourceId="eu.siacs.conversations:id/speed_dial").exists:
        log("✓ Found speed_dial - user is logged in!", SCRIPT_NAME)
        return True

    if d(resourceId="eu.siacs.conversations:id/action_search").exists:
        log("✓ Found action_search - user is logged in!", SCRIPT_NAME)
        return True

    # Fallback to text-based check (language-dependent)
    if d(text="Contacts").exists:
        log("✓ Found 'Contacts' text - user is logged in!", SCRIPT_NAME)
        return True

    log("User is not logged in", SCRIPT_NAME)
    return False


def handle_welcome_screen():
    """Handle the initial welcome screen"""
    log("Checking for welcome screen...", SCRIPT_NAME)

    # Use resource ID (stable) instead of text (language-dependent)
    use_existing_button = d(resourceId="eu.siacs.conversations:id/use_existing")

    if not use_existing_button.exists:
        log("Not on welcome screen (may already be past it)", SCRIPT_NAME)
        return False

    log("✓ Found welcome screen", SCRIPT_NAME)
    log("Clicking 'I already have an account'...", SCRIPT_NAME)
    use_existing_button.click()
    time.sleep(1)
    wait_for_ui_stable(d, timeout=TIMEOUT_NORMAL, script_name=SCRIPT_NAME)
    return True


def submit_login():
    """Click the Save/Next button to submit login"""
    log("Submitting login...", SCRIPT_NAME)

    save_button = d(resourceId="eu.siacs.conversations:id/save_button")
    if not save_button.exists:
        log("[ERROR] Save button not found", SCRIPT_NAME)
        return False

    save_button.click()
    log("✓ Clicked Save button", SCRIPT_NAME)
    time.sleep(1)
    return True


def handle_permissions(max_permissions=3):
    """
    Handle system permission dialogs (READ_CONTACTS, POST_NOTIFICATIONS).
    These appear AFTER the avatar screen.

    NOTE: If permissions are pre-granted via verify_exploit.sh,
    these dialogs won't appear, which is ideal.
    """
    log("Checking for system permission dialogs...", SCRIPT_NAME)
    log("(If pre-granted, these dialogs won't appear - that's optimal)", SCRIPT_NAME)

    permissions_handled = 0

    for attempt in range(max_permissions):
        time.sleep(0.5)

        # Check if we're on a permission dialog
        result = subprocess.run(
            ["adb", "shell", "dumpsys", "window", "displays"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if "permissioncontroller" not in result.stdout.lower():
            if attempt == 0:
                log(
                    "✓ No permission dialogs - likely pre-granted (optimal)",
                    SCRIPT_NAME,
                )
            else:
                log(
                    f"✓ No more permission dialogs after handling {permissions_handled}",
                    SCRIPT_NAME,
                )
            break

        log(f"✓ Permission dialog detected (#{attempt + 1})", SCRIPT_NAME)

        # Try to click Allow button (try both cases)
        clicked = False
        if d(text="Allow").exists:
            log("Clicking 'Allow'...", SCRIPT_NAME)
            d(text="Allow").click()
            clicked = True
        elif d(text="ALLOW").exists:
            log("Clicking 'ALLOW'...", SCRIPT_NAME)
            d(text="ALLOW").click()
            clicked = True

        if clicked:
            permissions_handled += 1
            time.sleep(1)
        else:
            log(
                "WARNING: Permission dialog present but no 'Allow' button found",
                SCRIPT_NAME,
            )
            break

    if permissions_handled > 0:
        log(f"✓ Handled {permissions_handled} permission dialog(s)", SCRIPT_NAME)
        wait_for_ui_stable(d, timeout=TIMEOUT_NORMAL, script_name=SCRIPT_NAME)

    return permissions_handled > 0


def main():
    log("=" * 60, SCRIPT_NAME)
    log("Conversations XMPP Login Automation", SCRIPT_NAME)
    log("=" * 60, SCRIPT_NAME)
    log(f"Username: {args.username}", SCRIPT_NAME)
    log(f"Password: {'*' * len(password)}", SCRIPT_NAME)

    try:
        # Wait for app to load
        log("\nWaiting for app to load...", SCRIPT_NAME)
        wait_for_ui_stable(d, timeout=TIMEOUT_SLOW, interval=1, script_name=SCRIPT_NAME)

        # Check if already logged in (idempotency)
        if check_if_logged_in():
            log("\n" + "=" * 60, SCRIPT_NAME)
            log("SUCCESS: User is already logged in", SCRIPT_NAME)
            log("=" * 60, SCRIPT_NAME)
            sys.exit(0)

        # Step 1: Handle welcome screen
        log("\n--- Step 1: Handle welcome screen ---", SCRIPT_NAME)
        handle_welcome_screen()

        # Step 2: Fill login form
        log("\n--- Step 2: Fill login form ---", SCRIPT_NAME)
        if not fill_login_form(d, args.username, password, script_name=SCRIPT_NAME):
            capture_failure_context(d, "Failed to fill login form", SCRIPT_NAME)
            sys.exit(1)

        # Step 3: Submit login
        log("\n--- Step 3: Submit login ---", SCRIPT_NAME)
        if not submit_login():
            capture_failure_context(d, "Failed to submit login", SCRIPT_NAME)
            sys.exit(1)

        # Step 4: Handle certificate dialog (appears immediately after submit)
        log("\n--- Step 4: Handle certificate dialog ---", SCRIPT_NAME)
        handle_certificate_dialog(d, timeout=TIMEOUT_NORMAL, script_name=SCRIPT_NAME)

        # Step 5: Handle publish avatar screen (appears after certificate)
        log("\n--- Step 5: Handle post-login setup ---", SCRIPT_NAME)
        handle_publish_avatar_screen(d, script_name=SCRIPT_NAME)

        # Step 6: Handle system permissions (appear after avatar screen)
        log("\n--- Step 6: Handle system permissions ---", SCRIPT_NAME)
        handle_permissions()

        # Step 7: Final verification
        log("\n--- Step 7: Final verification ---", SCRIPT_NAME)
        time.sleep(1)

        if check_if_logged_in():
            log("\n" + "=" * 60, SCRIPT_NAME)
            log("SUCCESS: Login completed successfully!", SCRIPT_NAME)
            log(f"User {args.username} is now logged in to Conversations", SCRIPT_NAME)
            log("=" * 60, SCRIPT_NAME)
            sys.exit(0)
        else:
            capture_failure_context(
                d,
                "Login verification failed - expected logged-in UI elements not found",
                SCRIPT_NAME,
            )
            sys.exit(1)

    except KeyboardInterrupt:
        log("\nInterrupted by user", SCRIPT_NAME)
        sys.exit(1)
    except Exception as e:
        log(f"[ERROR] Unexpected error: {e}", SCRIPT_NAME)
        import traceback

        traceback.print_exc(file=sys.stderr)
        capture_failure_context(d, f"Unexpected error: {e}", SCRIPT_NAME)
        sys.exit(1)


if __name__ == "__main__":
    main()
