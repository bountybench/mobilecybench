#!/usr/bin/env python3
"""
Login automation for SimpleLogin Android app.

Usage:
    python login.py --username testuser@gmail.com --password Passw0rd123
"""
import argparse
import sys
import time

from utils.ui_utils import (
    click_then_expect,
    initialize_ui_automation,
    wait_for_ui_stable,
)

PACKAGE = "io.simplelogin.android.fdroid"
SCRIPT_NAME = "simplelogin-login"


def log(msg):
    print(f"[{SCRIPT_NAME}] {msg}", file=sys.stderr)


def login(d, username, password):
    """Log in to SimpleLogin via the UI."""
    log("Launching app...")
    d.app_start(PACKAGE, wait=True, use_monkey=True)
    log("Waiting for login screen...")
    wait_for_ui_stable(d, timeout=10)

    # Fill email
    email_field = d(text="Email address")
    if not email_field.wait(timeout=15):
        log("ERROR: Email field not found")
        return False
    log("Filling email...")
    email_field.set_text(username)
    time.sleep(0.3)

    # Fill password
    password_field = d(text="Password")
    if not password_field.wait(timeout=5):
        log("ERROR: Password field not found")
        return False
    log("Filling password...")
    password_field.set_text(password)
    time.sleep(0.3)

    # Hide keyboard
    d.press("back")
    time.sleep(0.3)

    # Tap login button and expect HomeActivity
    log("Clicking Sign in...")
    login_btn = d(resourceId=f"{PACKAGE}:id/loginButton")

    def home_loaded():
        try:
            app = d.app_current()
            return "HomeActivity" in (app.get("activity") or "")
        except Exception:
            return False

    if not click_then_expect(d, login_btn, home_loaded, timeout=15):
        log("ERROR: Login did not reach HomeActivity")
        return False

    log("Login successful — HomeActivity reached")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    d = initialize_ui_automation()
    if not login(d, args.username, args.password):
        sys.exit(1)


if __name__ == "__main__":
    main()
