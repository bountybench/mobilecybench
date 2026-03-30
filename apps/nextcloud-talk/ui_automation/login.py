#!/usr/bin/env python3
"""
Log in to Nextcloud Talk on the emulator via the browser-based login flow.

Flow:
1. Server URL screen (native) -> enter URL, tap arrow
2. Browser handoff (native) -> wait for Chrome
3. Chrome connect page -> tap "Log in"
4. Chrome login form -> fill username/password, tap "Log in"
5. Chrome grant page -> tap "Grant access"
6. Main conversation list (native) -> verify logged in

Usage:
    python login.py --username admin --password secretpass
    python login.py --username admin --user-key admin_password
"""

import argparse
import json
import os
import sys
import time

import uiautomator2 as u2

from utils.ui_utils import click_then_expect

SCRIPT_NAME = "nc_login"
PACKAGE = "com.nextcloud.talk2"
BROWSER_PACKAGE = "com.android.chrome"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SECRETS_PATH = os.path.join(SCRIPT_DIR, "../secrets.json")
DEFAULT_METADATA_PATH = os.path.join(SCRIPT_DIR, "../metadata.json")


def get_default_server_url():
    with open(DEFAULT_METADATA_PATH, encoding="utf-8") as f:
        metadata = json.load(f)
    server = metadata.get("emulator_server")
    if not server:
        raise ValueError("metadata.json missing required field: emulator_server")
    if "://" not in server:
        raise ValueError(
            "metadata.json emulator_server must include a scheme (expected http:// or https://)"
        )
    return server


def log(msg):
    print(f"[{SCRIPT_NAME}] {msg}", file=sys.stderr, flush=True)


def current_package(d):
    return d.app_current().get("package", "")


def parse_args():
    parser = argparse.ArgumentParser(description="Nextcloud Talk login automation")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default=None, help="Direct password")
    parser.add_argument("--user-key", default=None, help="Key in secrets.json")
    parser.add_argument("--secrets", default=DEFAULT_SECRETS_PATH)
    parser.add_argument("--server-url", default=get_default_server_url())
    return parser.parse_args()


def get_password(args):
    if args.password:
        return args.password
    key = args.user_key or "admin_password"
    with open(args.secrets) as f:
        secrets = json.load(f)
    if key not in secrets:
        log(f"ERROR: Key '{key}' not found in {args.secrets}")
        sys.exit(1)
    return secrets[key]


def is_logged_in(d):
    """Check if we're on the main conversation list."""
    if d(text="Join a conversation or start a new one").exists:
        return True
    if d(resourceId=f"{PACKAGE}:id/floatingActionButton").exists:
        return True
    if d(resourceId=f"{PACKAGE}:id/dialogName").exists:
        return True
    return False


def on_ssl_cert_dialog(d):
    return d(
        resourceId="android:id/alertTitle", text="Check out the certificate"
    ).exists


def on_server_url_screen(d):
    return d(resourceId=f"{PACKAGE}:id/serverEntryTextInputEditText").exists


def on_browser_login_handoff_screen(d):
    return (
        current_package(d) == PACKAGE
        and d(resourceId=f"{PACKAGE}:id/cancel_login_btn").exists
    )


def on_chrome_welcome_screen(d):
    return (
        current_package(d) == BROWSER_PACKAGE
        and d(text="Use without an account", className="android.widget.Button").exists
    )


def on_chrome_notifications_dialog(d):
    return (
        current_package(d) == BROWSER_PACKAGE
        and d(
            resourceId=f"{BROWSER_PACKAGE}:id/negative_button", text="No thanks"
        ).exists
    )


def on_connect_page(d):
    return (
        current_package(d) == BROWSER_PACKAGE
        and d(text="Log in", className="android.widget.Button").exists
    )


def on_login_form(d):
    return (
        current_package(d) == BROWSER_PACKAGE and d(text="Log in to Nextcloud").exists
    )


def on_grant_access_page(d):
    return (
        current_package(d) == BROWSER_PACKAGE
        and d(text="Grant access", className="android.widget.Button").exists
    )


def on_account_connected_page(d):
    return current_package(d) == BROWSER_PACKAGE and d(text="Account connected").exists


def wait_for_condition(condition, timeout=30, interval=1):
    start = time.time()
    while time.time() - start < timeout:
        if condition():
            return True
        time.sleep(interval)
    return False


def wait_for_browser(d, timeout=30):
    log("Waiting for external browser")
    if not wait_for_condition(
        lambda: current_package(d) == BROWSER_PACKAGE
        or on_browser_login_handoff_screen(d),
        timeout=timeout,
    ):
        log("ERROR: Browser login handoff did not appear")
        sys.exit(1)

    if on_browser_login_handoff_screen(d):
        if not wait_for_condition(
            lambda: current_package(d) == BROWSER_PACKAGE, timeout=timeout
        ):
            log("ERROR: Chrome did not open after browser handoff screen")
            sys.exit(1)

    log("External browser opened")


def handle_chrome_first_run(d):
    while True:
        if on_chrome_welcome_screen(d):
            log("Chrome first run: choosing 'Use without an account'")
            d(text="Use without an account", className="android.widget.Button").click()
            time.sleep(2)
            continue

        if on_chrome_notifications_dialog(d):
            log("Chrome first run: dismissing notifications prompt")
            d(
                resourceId=f"{BROWSER_PACKAGE}:id/negative_button", text="No thanks"
            ).click()
            time.sleep(2)
            continue

        return


def handle_server_url(d, server_url):
    """Enter server URL and submit."""
    log("Step 1: Server URL screen")
    server_field = d(resourceId=f"{PACKAGE}:id/serverEntryTextInputEditText")
    server_field.set_text(server_url)
    time.sleep(0.5)

    arrow = d(resourceId=f"{PACKAGE}:id/text_input_end_icon")
    if not click_then_expect(
        d,
        arrow,
        lambda: current_package(d) == BROWSER_PACKAGE
        or on_browser_login_handoff_screen(d)
        or on_ssl_cert_dialog(d),
        timeout=30,
    ):
        log("ERROR: Browser handoff did not start after submitting server URL")
        sys.exit(1)

    # Accept self-signed certificate if prompted
    if on_ssl_cert_dialog(d):
        log("Accepting SSL certificate")
        d(resourceId="android:id/button1", text="Yes").click()
        time.sleep(2)
        # After accepting, the app retries the connection — tap arrow again
        if on_server_url_screen(d):
            arrow = d(resourceId=f"{PACKAGE}:id/text_input_end_icon")
            if not click_then_expect(
                d,
                arrow,
                lambda: current_package(d) == BROWSER_PACKAGE
                or on_browser_login_handoff_screen(d),
                timeout=30,
            ):
                log("ERROR: Browser handoff did not start after accepting certificate")
                sys.exit(1)

    log("Server URL submitted")


def handle_connect_page(d):
    """Tap 'Log in' on the browser connect page."""
    log("Step 2: Browser connect page")
    deadline = time.time() + 60
    while time.time() < deadline:
        handle_chrome_first_run(d)

        if on_login_form(d) or on_grant_access_page(d):
            log("Login form or grant page already visible")
            return

        if on_connect_page(d):
            login_btn = d(text="Log in", className="android.widget.Button")
            # Chrome may have a cached session — grant page can appear directly
            if not click_then_expect(
                d,
                login_btn,
                lambda: on_login_form(d) or on_grant_access_page(d),
                timeout=20,
            ):
                log("ERROR: Login form did not appear")
                sys.exit(1)
            log("Login form or grant page loaded")
            return

        time.sleep(1)

    log("ERROR: Connect page did not appear in Chrome")
    sys.exit(1)


def handle_login_form(d, username, password):
    """Fill and submit the browser login form."""
    log("Step 3: Filling login form")

    # Chrome may have a cached session — skip if already on grant page
    if on_grant_access_page(d):
        log("Grant page already visible (cached session), skipping login form")
        return

    if not wait_for_condition(lambda: on_login_form(d), timeout=20):
        log("ERROR: Login form is not visible")
        sys.exit(1)

    user_field = d(className="android.widget.EditText", instance=0)
    pwd_field = d(className="android.widget.EditText", instance=1)

    if not user_field.exists or not pwd_field.exists:
        log("ERROR: Could not find Chrome login form fields")
        sys.exit(1)

    user_field.set_text(username)
    time.sleep(0.3)

    pwd_field.set_text(password)
    time.sleep(0.3)

    login_btn = d(text="Log in", className="android.widget.Button")
    if login_btn.exists:
        if not click_then_expect(
            d, login_btn, lambda: on_grant_access_page(d), timeout=30
        ):
            log("ERROR: Grant access page did not appear after login")
            sys.exit(1)
    else:
        d.press("enter")
        if not wait_for_condition(lambda: on_grant_access_page(d), timeout=30):
            log("ERROR: Grant access page did not appear after login")
            sys.exit(1)

    log("Login form submitted")
    log("Grant access page loaded")


def handle_grant_access(d):
    """Tap 'Grant access' and return to the app."""
    log("Step 4: Granting access")
    grant_btn = d(text="Grant access", className="android.widget.Button")

    if not click_then_expect(
        d, grant_btn, lambda: on_account_connected_page(d), timeout=20
    ):
        log("ERROR: Account connected page did not appear after granting access")
        sys.exit(1)

    log("Access granted, returning to app")
    d.app_start(PACKAGE, wait=True)

    if not wait_for_condition(lambda: is_logged_in(d), timeout=45):
        log("ERROR: Main screen not reached after returning to app")
        sys.exit(1)
    log("Main screen reached")


def main():
    args = parse_args()
    password = get_password(args)

    log(f"Logging in {args.username} on {PACKAGE}")

    d = u2.connect()

    # Launch app
    d.app_start(PACKAGE, wait=True)
    time.sleep(3)

    # Already logged in?
    if is_logged_in(d):
        log("Already logged in")
        sys.exit(0)

    # Run login flow
    if on_server_url_screen(d):
        handle_server_url(d, args.server_url)

    wait_for_browser(d)
    handle_chrome_first_run(d)
    handle_connect_page(d)
    handle_login_form(d, args.username, password)
    handle_grant_access(d)

    log("SUCCESS: Login complete")


if __name__ == "__main__":
    main()
