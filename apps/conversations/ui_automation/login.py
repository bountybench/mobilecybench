#!/usr/bin/env python3
"""
Unified login automation for Conversations XMPP app.

Auto-detects the appropriate flow:
- First-time login: Welcome screen → Login form → Certificate → Avatar → Permissions
- Add account: Main screen → Manage accounts → Add account → Login form → Certificate → Avatar

Usage:
    # Login with password from secrets.json
    python login.py --username user1@10.0.2.2 --user-key user1_password

    # Login with direct password
    python login.py --username agentuser@10.0.2.2 --password agentpass

    # Force add-account flow (even if no accounts exist)
    python login.py --username user1@10.0.2.2 --user-key user1_password --add-account
"""
import argparse
import json
import os
import subprocess
import sys
import time

import uiautomator2 as u2
from ui_automation_utils import (
    TIMEOUT_FAST,
    TIMEOUT_NORMAL,
    TIMEOUT_SLOW,
    capture_failure_context,
    click_then_expect,
    fill_login_form,
    handle_certificate_dialog,
    handle_publish_avatar_screen,
    log,
    press_back_then_expect,
    wait_for_screen_change,
    wait_for_ui_stable,
)

SCRIPT_NAME = "login"
PACKAGE = "eu.siacs.conversations"
MAX_BACK_ATTEMPTS = 5

# Get script directory for relative paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SECRETS_PATH = os.path.join(SCRIPT_DIR, "../secrets.json")


def parse_args():
    parser = argparse.ArgumentParser(description="Conversations XMPP login automation")
    parser.add_argument(
        "--secrets", default=DEFAULT_SECRETS_PATH, help="Path to secrets.json"
    )
    parser.add_argument("--username", default="user1@10.0.2.2", help="XMPP username")
    parser.add_argument(
        "--user-key", default="user1_password", help="Key in secrets.json for password"
    )
    parser.add_argument(
        "--password", default=None, help="Direct password (overrides secrets.json)"
    )
    parser.add_argument(
        "--add-account",
        action="store_true",
        help="Force add-account flow (for adding secondary account)",
    )
    return parser.parse_args()


def get_password(args):
    """Get password from args or secrets.json"""
    if args.password:
        return args.password
    try:
        with open(args.secrets, "r") as f:
            secrets = json.load(f)
    except FileNotFoundError:
        log(f"[ERROR] Secrets file not found: {args.secrets}", SCRIPT_NAME)
        sys.exit(1)
    if args.user_key not in secrets:
        log(
            f"[ERROR] Key '{args.user_key}' not found in {args.secrets}. "
            f"Available keys: {list(secrets.keys())}",
            SCRIPT_NAME,
        )
        sys.exit(1)
    return secrets[args.user_key]


# =============================================================================
# Detection helpers
# =============================================================================


def check_if_logged_in(d):
    """Check if any user is logged in (main screen indicators)."""
    log("Checking if logged in...", SCRIPT_NAME)

    if d(resourceId="eu.siacs.conversations:id/speed_dial").exists:
        log("✓ Found speed_dial - user is logged in", SCRIPT_NAME)
        return True

    if d(resourceId="eu.siacs.conversations:id/fab").exists:
        log("✓ Found fab - user is logged in", SCRIPT_NAME)
        return True

    if d(resourceId="eu.siacs.conversations:id/action_search").exists:
        log("✓ Found action_search - user is logged in", SCRIPT_NAME)
        return True

    if d(text="Start chat").exists:
        log("✓ Found 'Start chat' - user is logged in", SCRIPT_NAME)
        return True

    if d(text="Contacts").exists:
        log("✓ Found 'Contacts' text - user is logged in", SCRIPT_NAME)
        return True

    log("No user is logged in", SCRIPT_NAME)
    return False


def check_on_welcome_screen(d):
    """Check if on the initial welcome screen."""
    return d(resourceId="eu.siacs.conversations:id/use_existing").exists


def check_user_in_accounts(d, username):
    """
    Check if specific user is in the account list.
    Must be called from main screen.
    Returns: 'found', 'not_found', or 'error'
    """
    log(f"Checking if {username} is in account list...", SCRIPT_NAME)

    overflow_menu = d(description="More options")
    if not overflow_menu.exists:
        log("Overflow menu not found", SCRIPT_NAME)
        return "error"

    manage_accounts = d(text="Manage accounts")
    if not click_then_expect(d, overflow_menu, manage_accounts, timeout=TIMEOUT_FAST):
        log("'Manage accounts' not found", SCRIPT_NAME)
        return "error"

    add_account_button = d(resourceId="eu.siacs.conversations:id/action_add_account")
    if not click_then_expect(
        d, manage_accounts, add_account_button, timeout=TIMEOUT_NORMAL
    ):
        log("Failed to navigate to Manage accounts", SCRIPT_NAME)
        return "error"

    if d(text=username).exists:
        log(f"✓ {username} is already in account list", SCRIPT_NAME)
        press_back_then_expect(d, d(description="More options"), timeout=TIMEOUT_FAST)
        return "found"
    else:
        log(f"{username} not found in account list", SCRIPT_NAME)
        return "not_found"


# =============================================================================
# Dialog and navigation recovery helpers
# =============================================================================


def dismiss_unexpected_dialogs(d):
    """Dismiss unexpected dialogs that may block the main UI.

    Handles known dialogs that can appear on launch:
    - "Battery optimizations enabled" (in-app) → clicks "Next"
    - "Let app always run in background?" (system) → clicks "Allow"
    """
    log("Checking for unexpected dialogs...", SCRIPT_NAME)
    dismissed = 0

    # Handle "Battery optimizations enabled" dialog.
    # Press back to dismiss it — clicking "Next" opens system Settings which
    # leaves the app in a bad navigation state.
    if d(text="Battery optimizations enabled").exists:
        log("Found 'Battery optimizations enabled' dialog, dismissing...", SCRIPT_NAME)
        pre_click = d.dump_hierarchy(compressed=True)
        d.press("back")
        wait_for_screen_change(d, pre_click, timeout=TIMEOUT_FAST)
        wait_for_ui_stable(d, timeout=TIMEOUT_NORMAL, script_name=SCRIPT_NAME)
        dismissed += 1
        log("✓ Dismissed battery optimization dialog", SCRIPT_NAME)

    if dismissed > 0:
        log(f"✓ Dismissed {dismissed} unexpected dialog(s)", SCRIPT_NAME)
    else:
        log("No unexpected dialogs found", SCRIPT_NAME)

    return dismissed


def _whitelist_battery_optimization():
    """Whitelist the app from battery optimization to prevent the dialog."""
    try:
        result = subprocess.run(
            ["adb", "shell", "dumpsys", "deviceidle", "whitelist", f"+{PACKAGE}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            log("✓ Battery optimization whitelisted", SCRIPT_NAME)
    except Exception as e:
        log(f"WARNING: Could not whitelist battery optimization: {e}", SCRIPT_NAME)


def navigate_to_main_screen(d):
    """Navigate back to the main screen if on a sub-screen within the app.

    Uses the 'Navigate up' button or back press to return to the main
    conversation list. Handles conversation views, settings, etc.

    Returns:
        True if on main screen (or welcome screen), False otherwise.
    """
    log("Not on main screen, attempting to navigate back...", SCRIPT_NAME)

    for i in range(MAX_BACK_ATTEMPTS):
        # Check if we've reached main screen
        if check_if_logged_in(d) or check_on_welcome_screen(d):
            log("✓ Navigated back to main screen", SCRIPT_NAME)
            return True

        # Check we're still in the app
        current = d.app_current()
        if current.get("package") != PACKAGE:
            log("Left the app, relaunching...", SCRIPT_NAME)
            d.app_start(PACKAGE, wait=True)
            wait_for_ui_stable(
                d, timeout=TIMEOUT_SLOW, interval=1, script_name=SCRIPT_NAME
            )
            continue

        # Try "Navigate up" button first (more reliable than back)
        nav_up = d(description="Navigate up")
        if nav_up.exists:
            log(f"Pressing Navigate up (attempt {i + 1})", SCRIPT_NAME)
            pre_click = d.dump_hierarchy(compressed=True)
            nav_up.click()
            wait_for_screen_change(d, pre_click, timeout=TIMEOUT_FAST)
            wait_for_ui_stable(d, timeout=TIMEOUT_NORMAL, script_name=SCRIPT_NAME)
        else:
            log(f"No Navigate up button, pressing back (attempt {i + 1})", SCRIPT_NAME)
            pre_click = d.dump_hierarchy(compressed=True)
            d.press("back")
            wait_for_screen_change(d, pre_click, timeout=TIMEOUT_FAST)
            wait_for_ui_stable(d, timeout=TIMEOUT_NORMAL, script_name=SCRIPT_NAME)

    # Final check
    return check_if_logged_in(d) or check_on_welcome_screen(d)


# =============================================================================
# First-time login flow
# =============================================================================


def handle_welcome_screen(d):
    """Handle the initial welcome screen."""
    log("Handling welcome screen...", SCRIPT_NAME)

    use_existing_button = d(resourceId="eu.siacs.conversations:id/use_existing")
    if not use_existing_button.exists:
        log("Not on welcome screen", SCRIPT_NAME)
        return False

    log("✓ Found welcome screen", SCRIPT_NAME)
    log("Clicking 'I already have an account'...", SCRIPT_NAME)

    jid_field = d(resourceId="eu.siacs.conversations:id/account_jid")
    if not click_then_expect(d, use_existing_button, jid_field, timeout=TIMEOUT_NORMAL):
        log("WARNING: Login form did not appear", SCRIPT_NAME)
    return True


def handle_permissions(d, max_permissions=3):
    """Handle system permission dialogs."""
    log("Checking for permission dialogs...", SCRIPT_NAME)

    permissions_handled = 0

    for attempt in range(max_permissions):
        wait_for_ui_stable(
            d, timeout=TIMEOUT_FAST, interval=0.3, script_name=SCRIPT_NAME
        )

        result = subprocess.run(
            ["adb", "shell", "dumpsys", "window", "displays"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if "permissioncontroller" not in result.stdout.lower():
            if attempt == 0:
                log("✓ No permission dialogs (likely pre-granted)", SCRIPT_NAME)
            break

        log(f"Permission dialog detected (#{attempt + 1})", SCRIPT_NAME)

        pre_click_hierarchy = d.dump_hierarchy(compressed=True)
        clicked = False

        for text in ["Allow", "ALLOW"]:
            if d(text=text).exists:
                d(text=text).click()
                clicked = True
                break

        if clicked:
            permissions_handled += 1
            wait_for_screen_change(d, pre_click_hierarchy, timeout=TIMEOUT_FAST)
        else:
            break

    if permissions_handled > 0:
        log(f"✓ Handled {permissions_handled} permission dialog(s)", SCRIPT_NAME)

    return permissions_handled


def first_time_login(d, username, password):
    """Execute first-time login flow."""
    log("\n--- First-time login flow ---", SCRIPT_NAME)

    # Step 1: Welcome screen
    log("\n[Step 1] Handle welcome screen", SCRIPT_NAME)
    handle_welcome_screen(d)

    # Step 2: Fill login form
    log("\n[Step 2] Fill login form", SCRIPT_NAME)
    if not fill_login_form(d, username, password, script_name=SCRIPT_NAME):
        return False

    # Step 3: Submit login
    log("\n[Step 3] Submit login", SCRIPT_NAME)
    if not submit_login(d):
        return False

    # Step 4: Handle certificate + retries
    log("\n[Step 4] Handle certificate dialog", SCRIPT_NAME)
    if not handle_certificate_with_retry(d):
        return False

    # Step 5: Handle avatar screen
    log("\n[Step 5] Handle post-login setup", SCRIPT_NAME)
    handle_publish_avatar_screen(d, script_name=SCRIPT_NAME)

    # Step 6: Handle permissions
    log("\n[Step 6] Handle permissions", SCRIPT_NAME)
    handle_permissions(d)

    return True


# =============================================================================
# Add-account flow
# =============================================================================


def navigate_to_add_account(d):
    """Navigate from Manage Accounts screen to Add Account form."""
    log("Clicking 'Add account' button...", SCRIPT_NAME)

    add_account_button = d(resourceId="eu.siacs.conversations:id/action_add_account")
    if not add_account_button.exists:
        log("[ERROR] 'Add account' button not found", SCRIPT_NAME)
        return False

    jid_field = d(resourceId="eu.siacs.conversations:id/account_jid")
    if not click_then_expect(d, add_account_button, jid_field, timeout=TIMEOUT_NORMAL):
        log("[ERROR] Login form did not appear", SCRIPT_NAME)
        return False

    log("✓ Navigated to Add Account screen", SCRIPT_NAME)
    return True


def add_account_login(d, username, password):
    """Execute add-account login flow (when already logged in as another user)."""
    log("\n--- Add-account login flow ---", SCRIPT_NAME)

    # Step 1: Navigate to Add Account (we should already be in Manage Accounts)
    log("\n[Step 1] Navigate to Add Account", SCRIPT_NAME)
    if not navigate_to_add_account(d):
        return False

    # Step 2: Fill login form
    log("\n[Step 2] Fill login form", SCRIPT_NAME)
    if not fill_login_form(d, username, password, script_name=SCRIPT_NAME):
        return False

    # Step 3: Submit login
    log("\n[Step 3] Submit login", SCRIPT_NAME)
    if not submit_login(d):
        return False

    # Step 4: Handle certificate + retries
    log("\n[Step 4] Handle certificate dialog", SCRIPT_NAME)
    if not handle_certificate_with_retry(d):
        return False

    # Step 5: Handle avatar screen
    log("\n[Step 5] Handle post-login setup", SCRIPT_NAME)
    handle_publish_avatar_screen(d, script_name=SCRIPT_NAME)

    return True


# =============================================================================
# Shared helpers
# =============================================================================


def submit_login(d):
    """Click the Save/Next button to submit login."""
    log("Submitting login...", SCRIPT_NAME)

    save_button = d(resourceId="eu.siacs.conversations:id/save_button")
    if not save_button.exists:
        log("[ERROR] Save button not found", SCRIPT_NAME)
        return False

    pre_click_hierarchy = d.dump_hierarchy(compressed=True)
    save_button.click()
    log("✓ Clicked Save button", SCRIPT_NAME)

    wait_for_screen_change(d, pre_click_hierarchy, timeout=TIMEOUT_NORMAL)
    return True


def handle_certificate_with_retry(d, max_attempts=3):
    """Handle certificate dialog with connection retries."""
    for attempt in range(max_attempts):
        handle_certificate_dialog(d, timeout=TIMEOUT_NORMAL, script_name=SCRIPT_NAME)
        time.sleep(2)

        # Check if we made it past login
        if (
            d(text="Publish avatar").exists
            or d(resourceId="eu.siacs.conversations:id/speed_dial").exists
            or d(resourceId="eu.siacs.conversations:id/fab").exists
        ):
            log("✓ Connection succeeded", SCRIPT_NAME)
            return True

        # Still on login form - retry
        save_button = d(resourceId="eu.siacs.conversations:id/save_button")
        if save_button.exists:
            log(
                f"Connection failed, retrying... (attempt {attempt + 2}/{max_attempts})",
                SCRIPT_NAME,
            )
            save_button.click()
            time.sleep(1)
        else:
            return True  # Not on login form, proceed

    log(f"✗ Connection failed after {max_attempts} attempts", SCRIPT_NAME)
    return False


def verify_login_success(d, username):
    """Verify login was successful."""
    log("\n[Final] Verifying login success...", SCRIPT_NAME)
    wait_for_ui_stable(d, timeout=TIMEOUT_FAST, script_name=SCRIPT_NAME)

    if check_if_logged_in(d):
        return True

    # For add-account, check if user is in account list
    if d(description="More options").exists:
        result = check_user_in_accounts(d, username)
        return result == "found"

    return False


# =============================================================================
# Main
# =============================================================================


def main():
    args = parse_args()
    password = get_password(args)

    log("=" * 60, SCRIPT_NAME)
    log("Conversations XMPP Login Automation", SCRIPT_NAME)
    log("=" * 60, SCRIPT_NAME)
    log(f"Username: {args.username}", SCRIPT_NAME)
    log(f"Password: {'*' * len(password)}", SCRIPT_NAME)
    if args.add_account:
        log("Mode: Force add-account", SCRIPT_NAME)

    # Whitelist battery optimization before launching to prevent the
    # "Battery optimizations enabled" dialog from appearing.
    _whitelist_battery_optimization()

    d = u2.connect()

    try:
        # Ensure the Conversations app is in the foreground
        log("\nEnsuring Conversations app is in foreground...", SCRIPT_NAME)
        current = d.app_current()
        current_pkg = current.get("package", "")
        if current_pkg != PACKAGE:
            log(
                f"App not in foreground (current: {current_pkg}). Launching {PACKAGE}...",
                SCRIPT_NAME,
            )
            try:
                d.app_start(PACKAGE, wait=True)
            except Exception as e:
                log(f"[ERROR] Failed to launch {PACKAGE}: {e}", SCRIPT_NAME)
                log(
                    "Is the app installed? Check with: adb shell pm list packages | grep conversations",
                    SCRIPT_NAME,
                )
                sys.exit(1)
            if not d.app_wait(PACKAGE, front=True, timeout=TIMEOUT_NORMAL):
                log(f"[ERROR] {PACKAGE} did not come to foreground", SCRIPT_NAME)
                sys.exit(1)
            log(f"✓ {PACKAGE} is now in foreground", SCRIPT_NAME)

        log("Waiting for app to load...", SCRIPT_NAME)
        wait_for_ui_stable(d, timeout=TIMEOUT_SLOW, interval=1, script_name=SCRIPT_NAME)

        # Dismiss any unexpected dialogs (e.g., battery optimization)
        dismiss_unexpected_dialogs(d)

        # Determine which flow to use
        on_welcome = check_on_welcome_screen(d)
        is_logged_in = check_if_logged_in(d)

        # If neither main screen nor welcome screen, try navigating back
        if not on_welcome and not is_logged_in:
            if navigate_to_main_screen(d):
                on_welcome = check_on_welcome_screen(d)
                is_logged_in = check_if_logged_in(d)

        if on_welcome and not args.add_account:
            # First-time login
            success = first_time_login(d, args.username, password)
        elif is_logged_in:
            # Check if target user is already logged in
            user_status = check_user_in_accounts(d, args.username)

            if user_status == "found":
                log("\n" + "=" * 60, SCRIPT_NAME)
                log(f"SUCCESS: {args.username} is already logged in", SCRIPT_NAME)
                log("=" * 60, SCRIPT_NAME)
                sys.exit(0)
            elif user_status == "not_found":
                # We're now in Manage Accounts, add the account
                success = add_account_login(d, args.username, password)
            else:
                log("[ERROR] Could not check account status", SCRIPT_NAME)
                sys.exit(1)
        else:
            # Shouldn't happen - neither welcome screen nor logged in
            log(
                "[ERROR] Unexpected state - not on welcome screen and not logged in",
                SCRIPT_NAME,
            )
            capture_failure_context(d, "Unexpected app state", SCRIPT_NAME)
            sys.exit(1)

        if not success:
            capture_failure_context(d, "Login flow failed", SCRIPT_NAME)
            sys.exit(1)

        # Verify success
        if verify_login_success(d, args.username):
            log("\n" + "=" * 60, SCRIPT_NAME)
            log("SUCCESS: Login completed!", SCRIPT_NAME)
            log(f"User {args.username} is now logged in", SCRIPT_NAME)
            log("=" * 60, SCRIPT_NAME)
            sys.exit(0)
        else:
            capture_failure_context(d, "Login verification failed", SCRIPT_NAME)
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
