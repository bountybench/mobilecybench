#!/usr/bin/env python3
"""
Log in to Nextcloud Talk on the emulator via the WebView login flow.

Flow:
1. Server URL screen (native) → enter URL, tap arrow
2. WebView "Connect to your account" → tap "Log in"
3. WebView login form → fill username/password, tap "Log in"
4. WebView "Grant access" → tap "Grant access"
5. Main conversation list (native) → verify logged in

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
DEFAULT_SERVER_URL = "http://10.0.2.2:8080"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SECRETS_PATH = os.path.join(SCRIPT_DIR, "../secrets.json")


def log(msg):
    print(f"[{SCRIPT_NAME}] {msg}", file=sys.stderr, flush=True)


def parse_args():
    parser = argparse.ArgumentParser(description="Nextcloud Talk login automation")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default=None, help="Direct password")
    parser.add_argument("--user-key", default=None, help="Key in secrets.json")
    parser.add_argument("--secrets", default=DEFAULT_SECRETS_PATH)
    parser.add_argument("--server-url", default=DEFAULT_SERVER_URL)
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


def on_server_url_screen(d):
    return d(resourceId=f"{PACKAGE}:id/serverEntryTextInputEditText").exists


def handle_server_url(d, server_url):
    """Enter server URL and submit."""
    log("Step 1: Server URL screen")
    server_field = d(resourceId=f"{PACKAGE}:id/serverEntryTextInputEditText")
    server_field.set_text(server_url)
    time.sleep(0.5)

    arrow = d(resourceId=f"{PACKAGE}:id/text_input_end_icon")
    # After tapping arrow, we expect the WebView to load with "Log in" button
    webview_login = d(text="Log in", className="android.widget.Button")
    if not click_then_expect(d, arrow, webview_login, timeout=30):
        log("ERROR: WebView did not load after submitting server URL")
        sys.exit(1)
    log("Server URL submitted, WebView loaded")


def handle_connect_page(d):
    """Tap 'Log in' on the 'Connect to your account' WebView page."""
    log("Step 2: Connect page — tapping 'Log in'")
    login_btn = d(text="Log in", className="android.widget.Button")
    # After tapping, we expect the login form with username field
    user_field = d(resourceId="user", className="android.widget.EditText")
    if not click_then_expect(d, login_btn, user_field, timeout=15):
        log("ERROR: Login form did not appear")
        sys.exit(1)
    log("Login form loaded")


def handle_login_form(d, username, password):
    """Fill and submit the WebView login form."""
    log("Step 3: Filling login form")
    user_field = d(resourceId="user", className="android.widget.EditText")
    user_field.click()
    time.sleep(0.3)
    user_field.set_text(username)
    time.sleep(0.3)

    pwd_field = d(resourceId="password", className="android.widget.EditText")
    pwd_field.click()
    time.sleep(0.3)
    pwd_field.set_text(password)
    time.sleep(0.3)

    # Hide keyboard
    d.press("back")
    time.sleep(0.5)

    log("Step 4: Submitting login")
    submit_btn = d(text="Log in", className="android.widget.Button")
    # After submit, expect either "Grant access" or "Account access"
    grant_btn = d(text="Grant access", className="android.widget.Button")
    if not click_then_expect(d, submit_btn, grant_btn, timeout=15):
        log("ERROR: Grant access page did not appear after login")
        sys.exit(1)
    log("Login submitted, grant access page loaded")


def handle_grant_access(d):
    """Tap 'Grant access' to complete the OAuth flow."""
    log("Step 5: Granting access")
    grant_btn = d(text="Grant access", className="android.widget.Button")

    def main_screen_reached():
        return is_logged_in(d)

    if not click_then_expect(d, grant_btn, main_screen_reached, timeout=20):
        log("ERROR: Main screen not reached after granting access")
        sys.exit(1)
    log("Access granted, main screen reached")


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

    handle_connect_page(d)
    handle_login_form(d, args.username, password)
    handle_grant_access(d)

    log("SUCCESS: Login complete")


if __name__ == "__main__":
    main()
