#!/usr/bin/env python3
"""
Automates Conversations XMPP login for Case 2: Adding account when user already signed in.
Extremely robust with idempotency - works even if user1 is already added.

Complete flow (verified manually):
1. Main screen → Overflow menu → Manage accounts
2. Tap "Add account" button
3. Login form → Fill username + password → Click Next
4. Certificate dialog → Click "Always"
5. Publish avatar screen → Click "Skip"
6. Verify logged in by checking for user1 account in manage accounts
"""
import argparse
import json
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

SCRIPT_NAME = "login_ui_case_2"

# Parse arguments
parser = argparse.ArgumentParser(
    description="Conversations XMPP login automation - Case 2"
)
parser.add_argument(
    "--secrets", default="../../secrets.json", help="Path to secrets.json"
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


def check_if_user1_already_added():
    """
    Check if user1 is already in the account list.
    Navigate to Manage Accounts and check.
    Returns: 'already_added', 'in_manage_accounts', or 'not_found'
    """
    log("Checking if user1 is already added...", SCRIPT_NAME)

    # Try to open overflow menu
    overflow_menu = d(description="More options")
    if not overflow_menu.exists:
        log("Overflow menu not found", SCRIPT_NAME)
        return "not_found"

    overflow_menu.click()
    time.sleep(0.5)

    # Click "Manage accounts"
    manage_accounts = d(text="Manage accounts")
    if not manage_accounts.exists:
        log("'Manage accounts' option not found", SCRIPT_NAME)
        return "not_found"

    manage_accounts.click()
    time.sleep(1)
    wait_for_ui_stable(d, timeout=TIMEOUT_NORMAL, script_name=SCRIPT_NAME)

    # Check if user1@10.0.2.2 exists in the account list
    if d(text=args.username).exists:
        log(f"✓ User {args.username} is already added!", SCRIPT_NAME)
        # Go back to main screen
        d.press("back")
        time.sleep(0.5)
        return "already_added"
    else:
        log(f"User {args.username} not found in account list", SCRIPT_NAME)
        log("Already in Manage Accounts - will add account from here", SCRIPT_NAME)
        return "in_manage_accounts"


def navigate_to_add_account_from_manage_accounts():
    """
    Add account when already in Manage Accounts screen.
    """
    log("Adding account from Manage Accounts screen...", SCRIPT_NAME)

    # Click Add account button using resource ID (stable)
    add_account_button = d(resourceId="eu.siacs.conversations:id/action_add_account")
    if not add_account_button.exists:
        log("[ERROR] 'Add account' button not found", SCRIPT_NAME)
        return False

    log("Tapping 'Add account' button...", SCRIPT_NAME)
    add_account_button.click()
    time.sleep(1)
    wait_for_ui_stable(d, timeout=TIMEOUT_NORMAL, script_name=SCRIPT_NAME)

    log("✓ Successfully navigated to Add Account screen", SCRIPT_NAME)
    return True


def navigate_to_add_account():
    """
    Navigate from main screen to Add Account screen.
    Assumes we're on the main logged-in screen.
    """
    log("Navigating to Add Account screen from main screen...", SCRIPT_NAME)

    # Open overflow menu
    overflow_menu = d(description="More options")
    if not overflow_menu.exists:
        log("[ERROR] Overflow menu not found - may not be on main screen", SCRIPT_NAME)
        return False

    log("Opening overflow menu...", SCRIPT_NAME)
    overflow_menu.click()
    time.sleep(0.5)

    # Click "Manage accounts"
    manage_accounts = d(text="Manage accounts")
    if not manage_accounts.exists:
        log("[ERROR] 'Manage accounts' option not found", SCRIPT_NAME)
        return False

    log("Tapping 'Manage accounts'...", SCRIPT_NAME)
    manage_accounts.click()
    time.sleep(1)
    wait_for_ui_stable(d, timeout=TIMEOUT_NORMAL, script_name=SCRIPT_NAME)

    # Click Add account button using resource ID (stable)
    add_account_button = d(resourceId="eu.siacs.conversations:id/action_add_account")
    if not add_account_button.exists:
        log("[ERROR] 'Add account' button not found", SCRIPT_NAME)
        return False

    log("Tapping 'Add account' button...", SCRIPT_NAME)
    add_account_button.click()
    time.sleep(1)
    wait_for_ui_stable(d, timeout=TIMEOUT_NORMAL, script_name=SCRIPT_NAME)

    log("✓ Successfully navigated to Add Account screen", SCRIPT_NAME)
    return True


def submit_login():
    """Click the Next button to submit login"""
    log("Submitting login...", SCRIPT_NAME)

    save_button = d(resourceId="eu.siacs.conversations:id/save_button")
    if not save_button.exists:
        log("[ERROR] Next button not found", SCRIPT_NAME)
        return False

    save_button.click()
    log("✓ Clicked Next button", SCRIPT_NAME)
    time.sleep(1)
    return True


def verify_account_added():
    """
    Verify that user1 was successfully added by checking Manage Accounts.
    Assumes we're back on the main screen.
    """
    log("Verifying account was added...", SCRIPT_NAME)

    # Wait a bit for the UI to settle
    time.sleep(1)

    # Open overflow menu
    overflow_menu = d(description="More options")
    if not overflow_menu.exists:
        log("[ERROR] Overflow menu not found for verification", SCRIPT_NAME)
        return False

    overflow_menu.click()
    time.sleep(0.5)

    # Click "Manage accounts"
    manage_accounts = d(text="Manage accounts")
    if not manage_accounts.exists:
        log("[ERROR] 'Manage accounts' not found for verification", SCRIPT_NAME)
        return False

    manage_accounts.click()
    time.sleep(1)
    wait_for_ui_stable(d, timeout=TIMEOUT_NORMAL, script_name=SCRIPT_NAME)

    # Check if user1 exists
    if d(text=args.username).exists:
        log(f"✓ Verified: {args.username} is in account list", SCRIPT_NAME)
        # Go back to main screen
        d.press("back")
        time.sleep(0.5)
        return True
    else:
        log(f"[ERROR] {args.username} not found in account list", SCRIPT_NAME)
        return False


def main():
    log("=" * 60, SCRIPT_NAME)
    log("Conversations XMPP Login Automation - Case 2", SCRIPT_NAME)
    log("Scenario: Adding account when user already signed in", SCRIPT_NAME)
    log("=" * 60, SCRIPT_NAME)
    log(f"Username: {args.username}", SCRIPT_NAME)
    log(f"Password: {'*' * len(password)}", SCRIPT_NAME)

    try:
        # Wait for app to load
        log("\nWaiting for app to load...", SCRIPT_NAME)
        wait_for_ui_stable(d, timeout=TIMEOUT_SLOW, interval=1, script_name=SCRIPT_NAME)

        # Check if user1 is already added (idempotency)
        check_result = check_if_user1_already_added()

        if check_result == "already_added":
            log("\n" + "=" * 60, SCRIPT_NAME)
            log("SUCCESS: User1 is already added to account list", SCRIPT_NAME)
            log("=" * 60, SCRIPT_NAME)
            sys.exit(0)
        elif check_result == "in_manage_accounts":
            # We're already in Manage Accounts, just click Add account button
            log(
                "\n--- Step 1: Navigate to Add Account (from Manage Accounts) ---",
                SCRIPT_NAME,
            )
            if not navigate_to_add_account_from_manage_accounts():
                capture_failure_context(
                    d, "Failed to click Add Account button", SCRIPT_NAME
                )
                sys.exit(1)
        else:
            # Need to navigate from main screen
            log(
                "\n--- Step 1: Navigate to Add Account (from main screen) ---",
                SCRIPT_NAME,
            )
            if not navigate_to_add_account():
                capture_failure_context(
                    d, "Failed to navigate to Add Account screen", SCRIPT_NAME
                )
                sys.exit(1)

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

        # Step 6: Final verification
        log("\n--- Step 6: Final verification ---", SCRIPT_NAME)
        if verify_account_added():
            log("\n" + "=" * 60, SCRIPT_NAME)
            log("SUCCESS: Account added successfully!", SCRIPT_NAME)
            log(f"User {args.username} is now in the account list", SCRIPT_NAME)
            log("=" * 60, SCRIPT_NAME)
            sys.exit(0)
        else:
            capture_failure_context(
                d,
                f"Account verification failed - {args.username} not found in account list",
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
