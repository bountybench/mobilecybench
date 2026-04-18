#!/usr/bin/env python3
"""
Login automation for Gotify push notification app.

Auto-detects the app state and performs the appropriate login flow:
- Already logged in (on MessagesActivity) → exit 0
- Fresh install (on LoginActivity) → full login flow
- Mid-flow states (partial login, crashed) → attempt recovery

Usage:
    # Login with password from metadata.json
    python login.py --username admin

    # Login with direct password
    python login.py --username admin --password mypassword
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
    log,
    wait_for_screen_change,
    wait_for_ui_stable,
)

SCRIPT_NAME = "login"
PACKAGE = "com.github.gotify"

# Get script directory for relative paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_METADATA_PATH = os.path.join(SCRIPT_DIR, "../metadata.json")


def parse_args():
    parser = argparse.ArgumentParser(description="Gotify login automation")
    parser.add_argument("--username", default="admin", help="Gotify username")
    parser.add_argument(
        "--password", default=None, help="Direct password (overrides metadata.json)"
    )
    parser.add_argument(
        "--metadata",
        default=DEFAULT_METADATA_PATH,
        help="Path to metadata.json",
    )
    return parser.parse_args()


def get_password(args):
    """Get password from args or metadata.json"""
    if args.password:
        return args.password
    try:
        with open(args.metadata, "r") as f:
            metadata = json.load(f)
    except FileNotFoundError:
        log(f"[ERROR] Metadata file not found: {args.metadata}", SCRIPT_NAME)
        sys.exit(1)
    if "password" not in metadata:
        log(
            f"[ERROR] Key 'password' not found in {args.metadata}. "
            f"Available keys: {list(metadata.keys())}",
            SCRIPT_NAME,
        )
        sys.exit(1)
    return metadata["password"]


# =============================================================================
# Detection helpers
# =============================================================================


def get_current_activity():
    """Get the current foreground activity name."""
    try:
        result = subprocess.run(
            ["adb", "shell", "dumpsys", "window", "displays"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.split("\n"):
            if "mCurrentFocus" in line or "mFocusedApp" in line:
                if "MessagesActivity" in line:
                    return "MessagesActivity"
                if "LoginActivity" in line:
                    return "LoginActivity"
        return "unknown"
    except Exception:
        return "unknown"


def check_if_logged_in(d):
    """Check if user is already logged in (on MessagesActivity)."""
    log("Checking if logged in...", SCRIPT_NAME)

    activity = get_current_activity()
    if activity == "MessagesActivity":
        log("Found MessagesActivity - user is logged in", SCRIPT_NAME)
        return True

    if d(resourceId="com.github.gotify:id/messages_list").exists:
        log("Found messages_list - user is logged in", SCRIPT_NAME)
        return True

    log("User is not logged in", SCRIPT_NAME)
    return False


def check_on_login_screen(d):
    """Check if on the login screen."""
    return d(resourceId="com.github.gotify:id/gotify_url_editext").exists


def check_credentials_visible(d):
    """Check if credential fields are already visible (mid-flow recovery)."""
    return d(resourceId="com.github.gotify:id/username_editext").exists


# =============================================================================
# Login flow
# =============================================================================


def login_flow(d, username, password):
    """Execute the full Gotify login flow with assertions between every step."""
    log("\n--- Gotify login flow ---", SCRIPT_NAME)

    # Use fast input IME to prevent keyboard from overlaying the form.
    # The login layout has a large logo + stacked fields inside a ScrollView,
    # so the soft keyboard easily pushes fields off-screen.
    log("Switching to fast input IME...", SCRIPT_NAME)
    d.set_input_ime(True)

    try:
        return _login_flow_inner(d, username, password)
    finally:
        # Always restore the default IME
        try:
            d.set_input_ime(False)
        except Exception:
            pass


def _login_flow_inner(d, username, password):
    """Inner login flow, called with fast IME active."""

    # Check if we're mid-flow (credentials already visible)
    if check_credentials_visible(d):
        log("Credential fields already visible (mid-flow recovery)", SCRIPT_NAME)
        return _fill_credentials_and_login(d, username, password)

    # Step 1: Enter server URL
    log("\n[Step 1] Enter server URL", SCRIPT_NAME)
    url_field = d(resourceId="com.github.gotify:id/gotify_url_editext")
    if not url_field.wait(timeout=TIMEOUT_SLOW):
        log("[ERROR] URL field did not appear", SCRIPT_NAME)
        return False

    url_field.clear_text()
    time.sleep(0.2)
    url_field.set_text("http://10.0.2.2:8080")
    time.sleep(0.3)
    log("Set server URL: http://10.0.2.2:8080", SCRIPT_NAME)

    # Step 2: Click "Check URL" → expect HTTP warning dialog or credential fields
    log(
        "\n[Step 2] Click 'Check URL' → expect HTTP warning or credential fields",
        SCRIPT_NAME,
    )
    check_url_btn = d(resourceId="com.github.gotify:id/checkurl")
    understand_btn = d(text="I Understand")

    def expect_after_checkurl():
        return (
            understand_btn.exists
            or d(resourceId="com.github.gotify:id/username_editext").exists
        )

    if not click_then_expect(
        d, check_url_btn, expect_after_checkurl, timeout=TIMEOUT_NORMAL
    ):
        log(
            "[ERROR] Neither HTTP warning nor credential fields appeared after Check URL",
            SCRIPT_NAME,
        )
        return False
    log("Check URL succeeded", SCRIPT_NAME)

    # Step 3: Dismiss HTTP warning dialog, then wait for credential fields.
    # IMPORTANT: In Gotify's LoginActivity, the HTTP warning dialog is non-blocking.
    # The /version API call runs in parallel. Credential fields appear when the API
    # responds, NOT when the dialog is dismissed. So we click "I Understand" once
    # (to dismiss the dialog) and then simply wait for the credential fields.
    log("\n[Step 3] Handle HTTP warning dialog", SCRIPT_NAME)
    username_field = d(resourceId="com.github.gotify:id/username_editext")
    if understand_btn.exists:
        log("Found HTTP warning dialog, clicking 'I Understand'...", SCRIPT_NAME)
        understand_btn.click()
        time.sleep(0.5)
        log("HTTP warning dismissed, waiting for server validation...", SCRIPT_NAME)

        # Wait for credential fields — they appear when the /version API call completes.
        # Use TIMEOUT_SLOW since the server may take time to respond.
        if not username_field.wait(timeout=TIMEOUT_SLOW):
            log(
                "[ERROR] Credential fields did not appear after dismissing HTTP warning "
                "(server may be unreachable)",
                SCRIPT_NAME,
            )
            return False
        log("Credential fields appeared", SCRIPT_NAME)
    else:
        # No HTTP warning — credential fields should already be visible
        if not username_field.wait(timeout=TIMEOUT_SLOW):
            log("[ERROR] Credential fields did not appear", SCRIPT_NAME)
            return False
        log("No HTTP warning (credential fields already visible)", SCRIPT_NAME)

    # Steps 4-7: Fill credentials and login
    return _fill_credentials_and_login(d, username, password)


def _fill_credentials_and_login(d, username, password):
    """Fill username/password and complete login. Used by both fresh and mid-flow paths."""

    # Step 4: Fill username
    log("\n[Step 4] Fill username", SCRIPT_NAME)
    username_field = d(resourceId="com.github.gotify:id/username_editext")
    if not username_field.wait(timeout=TIMEOUT_NORMAL):
        log("[ERROR] Username field not found", SCRIPT_NAME)
        return False
    username_field.clear_text()
    time.sleep(0.2)
    username_field.set_text(username)
    time.sleep(0.3)
    log(f"Set username: {username}", SCRIPT_NAME)

    # Verify username was set
    if not username_field.exists:
        log("[ERROR] Username field disappeared after setting text", SCRIPT_NAME)
        return False

    # Step 5: Fill password
    log("\n[Step 5] Fill password", SCRIPT_NAME)
    password_field = d(resourceId="com.github.gotify:id/password_editext")
    if not password_field.wait(timeout=TIMEOUT_NORMAL):
        log("[ERROR] Password field not found", SCRIPT_NAME)
        return False
    password_field.set_text(password)
    time.sleep(0.3)
    log("Set password: ****", SCRIPT_NAME)

    # Step 6: Click Login → expect "Create Client" dialog or MessagesActivity
    log(
        "\n[Step 6] Click Login → expect Create Client dialog or MessagesActivity",
        SCRIPT_NAME,
    )
    login_btn = d(resourceId="com.github.gotify:id/login")

    # Fast path: if the button is already visible, click it directly.
    # This skips the back-press dance below which, on emulators where the
    # fast-input IME suppresses the soft keyboard, sometimes navigates away
    # from LoginActivity instead of just defocusing. That regression was
    # observed on GKE under the bumped memory limits (the back press took
    # effect reliably instead of being absorbed by keyboard dismissal).
    if not login_btn.exists:
        # Defocus text fields first so scrolling works
        d.press("back")
        time.sleep(0.5)

        # Dismiss NotificationShade or other system overlays if they appeared
        current_focus = d.info.get("currentPackageName", "")
        if current_focus and current_focus != "com.github.gotify":
            log(
                f"Left gotify activity ({current_focus}); re-launching",
                SCRIPT_NAME,
            )
            subprocess.run(
                [
                    "adb",
                    "shell",
                    "monkey",
                    "-p",
                    PACKAGE,
                    "-c",
                    "android.intent.category.LAUNCHER",
                    "1",
                ],
                capture_output=True,
                timeout=10,
            )
            time.sleep(1)

        if not login_btn.wait(timeout=TIMEOUT_NORMAL):
            # Button may be off-screen, try scrolling
            log("Login button not visible, scrolling...", SCRIPT_NAME)
            try:
                d(scrollable=True).scroll.to(resourceId="com.github.gotify:id/login")
            except Exception:
                pass
            if not login_btn.wait(timeout=TIMEOUT_FAST):
                log("[ERROR] Login button not found even after scrolling", SCRIPT_NAME)
                return False

    create_btn = d(text="Create")

    def expect_after_login():
        return (
            create_btn.exists
            or get_current_activity() == "MessagesActivity"
            or d(resourceId="com.github.gotify:id/messages_list").exists
        )

    if not click_then_expect(d, login_btn, expect_after_login, timeout=TIMEOUT_SLOW):
        log(
            "[ERROR] Neither Create Client dialog nor MessagesActivity appeared after Login",
            SCRIPT_NAME,
        )
        return False
    log("Login clicked successfully", SCRIPT_NAME)

    # Step 7: Handle "Create Client" dialog → expect MessagesActivity
    log("\n[Step 7] Handle 'Create Client' dialog", SCRIPT_NAME)
    if create_btn.exists:
        log("Found 'Create Client' dialog, clicking 'Create'...", SCRIPT_NAME)

        def expect_after_create():
            return (
                get_current_activity() == "MessagesActivity"
                or d(resourceId="com.github.gotify:id/messages_list").exists
            )

        if not click_then_expect(
            d, create_btn, expect_after_create, timeout=TIMEOUT_SLOW
        ):
            # May have permission dialogs first, continue anyway
            log(
                "MessagesActivity not immediately visible after Create, checking permissions...",
                SCRIPT_NAME,
            )
    else:
        log("No 'Create Client' dialog found", SCRIPT_NAME)

    # Step 8: Handle permission dialogs
    log("\n[Step 8] Handle permission dialogs", SCRIPT_NAME)
    handle_permissions(d)

    # Step 9: Verify we reached MessagesActivity
    log("\n[Step 9] Verify login success", SCRIPT_NAME)
    for _ in range(TIMEOUT_SLOW):
        if get_current_activity() == "MessagesActivity":
            log("MessagesActivity detected - login successful", SCRIPT_NAME)
            return True
        if d(resourceId="com.github.gotify:id/messages_list").exists:
            log("Messages list detected - login successful", SCRIPT_NAME)
            return True
        time.sleep(1)

    log("[ERROR] MessagesActivity did not appear within timeout", SCRIPT_NAME)
    return False


def handle_permissions(d, max_permissions=3):
    """Handle system permission dialogs."""
    log("Checking for permission dialogs...", SCRIPT_NAME)
    permissions_handled = 0

    for attempt in range(max_permissions):
        time.sleep(1)

        result = subprocess.run(
            ["adb", "shell", "dumpsys", "window", "displays"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if "permissioncontroller" not in result.stdout.lower():
            if attempt == 0:
                log("No permission dialogs (likely pre-granted)", SCRIPT_NAME)
            break

        log(f"Permission dialog detected (#{attempt + 1})", SCRIPT_NAME)

        allow_btn = d(text="Allow")
        if not allow_btn.exists:
            allow_btn = d(text="ALLOW")

        if allow_btn.exists:
            # Click allow and expect the dialog to disappear
            pre_hierarchy = d.dump_hierarchy(compressed=True)
            allow_btn.click()
            permissions_handled += 1
            wait_for_screen_change(d, pre_hierarchy, timeout=TIMEOUT_FAST)
        else:
            break

    if permissions_handled > 0:
        log(f"Handled {permissions_handled} permission dialog(s)", SCRIPT_NAME)

    return permissions_handled


# =============================================================================
# Main
# =============================================================================


def main():
    args = parse_args()
    password = get_password(args)

    log("=" * 60, SCRIPT_NAME)
    log("Gotify Login Automation", SCRIPT_NAME)
    log("=" * 60, SCRIPT_NAME)
    log(f"Username: {args.username}", SCRIPT_NAME)
    log(f"Password: {'*' * len(password)}", SCRIPT_NAME)

    d = u2.connect()

    try:
        log("\nWaiting for app to load...", SCRIPT_NAME)
        wait_for_ui_stable(d, timeout=TIMEOUT_SLOW, interval=1, script_name=SCRIPT_NAME)

        # --- Handle multiple starting states ---

        # State 1: Already logged in
        if check_if_logged_in(d):
            log("\n" + "=" * 60, SCRIPT_NAME)
            log("SUCCESS: Already logged in", SCRIPT_NAME)
            log("=" * 60, SCRIPT_NAME)
            sys.exit(0)

        # State 2: On login screen (fresh install)
        if check_on_login_screen(d):
            log("Detected: Login screen (fresh install)", SCRIPT_NAME)
            success = login_flow(d, args.username, password)

        # State 3: Credential fields visible (mid-flow / partial login)
        elif check_credentials_visible(d):
            log("Detected: Credentials visible (mid-flow recovery)", SCRIPT_NAME)
            d.set_input_ime(True)
            try:
                success = _fill_credentials_and_login(d, args.username, password)
            finally:
                try:
                    d.set_input_ime(False)
                except Exception:
                    pass

        # State 4: Unknown state — try launching the app
        else:
            log("Detected: Unknown state, launching app...", SCRIPT_NAME)
            subprocess.run(
                [
                    "adb",
                    "shell",
                    "monkey",
                    "-p",
                    PACKAGE,
                    "-c",
                    "android.intent.category.LAUNCHER",
                    "1",
                ],
                capture_output=True,
                timeout=10,
            )
            time.sleep(3)
            wait_for_ui_stable(d, timeout=TIMEOUT_NORMAL, script_name=SCRIPT_NAME)

            if check_if_logged_in(d):
                log("\n" + "=" * 60, SCRIPT_NAME)
                log("SUCCESS: Already logged in (after app launch)", SCRIPT_NAME)
                log("=" * 60, SCRIPT_NAME)
                sys.exit(0)

            if check_on_login_screen(d):
                success = login_flow(d, args.username, password)
            else:
                log("[ERROR] Cannot determine app state after launch", SCRIPT_NAME)
                capture_failure_context(d, "Unknown app state", SCRIPT_NAME)
                sys.exit(1)

        if not success:
            capture_failure_context(d, "Login flow failed", SCRIPT_NAME)
            sys.exit(1)

        log("\n" + "=" * 60, SCRIPT_NAME)
        log("SUCCESS: Login completed!", SCRIPT_NAME)
        log(f"User {args.username} is now logged in", SCRIPT_NAME)
        log("=" * 60, SCRIPT_NAME)
        sys.exit(0)

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
