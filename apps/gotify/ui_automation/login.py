#!/usr/bin/env python3
"""
Login automation for Gotify Android app.

Uses the shared uiautomator2-based utilities from utils.ui_utils.

Usage:
    python login.py --server-url http://localhost:8080 --username agent --password agentpass
"""
import argparse
import os
import subprocess
import sys
import time
from urllib.parse import urlparse

# Add project root to path for shared utils
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from utils.ui_utils import (
    initialize_ui_automation,
    wait_for_ui_stable,
)

SCRIPT_NAME = "gotify-login"
PACKAGE = "com.github.gotify"

os.environ.setdefault("UI_TARGET_PACKAGE", PACKAGE)


def log(msg):
    print(f"[{SCRIPT_NAME}] {msg}", file=sys.stderr)


def setup_adb_forwarding(port):
    """Set up ADB reverse port forwarding so the emulator can reach the host."""
    log(f"Setting up ADB port forwarding for port {port}...")
    result = subprocess.run(
        ["adb", "reverse", f"tcp:{port}", f"tcp:{port}"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        log(f"ADB port forwarding active: emulator localhost:{port} -> host localhost:{port}")
    else:
        log("WARNING: ADB port forwarding failed, continuing anyway...")


def _setup_anr_watcher(d):
    """Register a watcher to auto-dismiss ANR dialogs throughout the login flow."""
    try:
        d.watcher.when("Wait").click()
        d.watcher.start()
        log("ANR watcher registered")
    except Exception as e:
        log(f"WARNING: Could not register ANR watcher: {e}")


def _set_text_with_retry(d, element, text, retries=5):
    """Set text on an element with retry logic to handle ANR interruptions."""
    for attempt in range(retries):
        try:
            element.set_text(text)
            return True
        except Exception:
            log(f"set_text failed (attempt {attempt + 1}/{retries}), retrying...")
            # Dismiss any ANR dialog that might be blocking
            wait_btn = d(resourceId="android:id/aerr_wait")
            if wait_btn.exists(timeout=2):
                wait_btn.click()
                time.sleep(2)
            else:
                time.sleep(1)
    log("ERROR: Failed to set text after retries")
    return False


def ensure_logged_in(d, server_url, username, password):
    """Log into the Gotify app if not already logged in."""

    # Check if already logged in
    if d(resourceId="com.github.gotify:id/messages").exists(timeout=3) or \
       d(resourceId="com.github.gotify:id/applications").exists(timeout=3):
        log("App is already logged in, skipping login")
        return 0

    # Navigate to login screen if needed
    url_field = d(resourceId="com.github.gotify:id/gotify_url_editext")
    if not url_field.exists(timeout=10):
        log("Not on login screen, restarting app...")
        d.app_start(PACKAGE, stop=True, wait=True, use_monkey=True)
        time.sleep(3)
        if not url_field.wait(timeout=10):
            if d(resourceId="com.github.gotify:id/messages").exists(timeout=3) or \
               d(resourceId="com.github.gotify:id/applications").exists(timeout=3):
                log("App is already logged in after restart")
                return 0
            log("ERROR: Could not reach login screen")
            return 1

    # Enter server URL
    log(f"Entering server URL: {server_url}")
    url_field.click()
    time.sleep(0.5)
    _set_text_with_retry(d, url_field, server_url)
    time.sleep(0.5)
    d.press("back")  # dismiss keyboard
    time.sleep(0.5)

    # Tap Check URL button
    check_btn = d(resourceId="com.github.gotify:id/checkurl")
    if not check_btn.wait(timeout=10):
        log("ERROR: Check URL button not found")
        return 1

    log("Tapping Check URL...")
    check_btn.click()
    time.sleep(2)

    # Handle SSL warning dialog ("I understand" / "I Understand")
    for _ in range(30):
        username_field = d(resourceId="com.github.gotify:id/username_editext")
        if username_field.exists(timeout=1):
            break
        # Try to dismiss SSL warning by text match first (most reliable)
        for text in ["I Understand", "I understand"]:
            btn = d(text=text)
            if btn.exists(timeout=1):
                btn.click()
                log(f"Dismissed SSL warning ('{text}')")
                time.sleep(1)
                break
        else:
            # Try generic dialog button as fallback
            understand_btn = d(resourceId="android:id/button1")
            if understand_btn.exists(timeout=1):
                understand_btn.click()
                time.sleep(0.5)
                continue
            time.sleep(0.5)

    # Enter username
    username_field = d(resourceId="com.github.gotify:id/username_editext")
    if not username_field.wait(timeout=10):
        log("ERROR: Username field not visible after URL check")
        return 1

    log(f"Entering username: {username}")
    _set_text_with_retry(d, username_field, username)
    time.sleep(0.5)

    # Scroll down to reveal password field (it's hidden by keyboard)
    d.swipe_ext("up", scale=0.5)
    time.sleep(1)

    # Enter password
    password_field = d(resourceId="com.github.gotify:id/password_editext")
    if not password_field.wait(timeout=15):
        log("ERROR: Password field not found")
        return 1

    log("Entering password...")
    _set_text_with_retry(d, password_field, password)
    time.sleep(1)

    # Tap Login button
    login_btn = d(resourceId="com.github.gotify:id/login")
    if not login_btn.exists(timeout=5):
        log("ERROR: Login button not found")
        return 1

    log("Tapping Login...")
    login_btn.click()
    time.sleep(2)

    # Handle Client Name dialog
    if d(text="Client Name").wait(timeout=20) or \
       d(resourceId="android:id/button1").exists(timeout=1) or \
       d(text="Create").exists(timeout=1):
        create_btn = d(resourceId="android:id/button1")
        if create_btn.exists(timeout=1):
            create_btn.click()
        else:
            d(text="Create").click_exists(timeout=1)
        time.sleep(1)

    # Handle permission dialogs
    _handle_permission_dialogs(d)

    # Verify login succeeded
    if d(resourceId="com.github.gotify:id/messages").wait(timeout=10) or \
       d(resourceId="com.github.gotify:id/applications").wait(timeout=5):
        log("Login successful")
        return 0

    log("WARNING: Could not confirm login success, but continuing")
    return 0


def _handle_permission_dialogs(d):
    """Dismiss permission and settings dialogs that appear after login."""
    idle_rounds = 0
    end_time = time.time() + 20

    while time.time() < end_time and idle_rounds < 6:
        acted = False

        # Check if we're in Android Settings (alarm/reminders screen)
        try:
            current = d.app_current()
            if current.get("package") == "com.android.settings":
                log("Detected Settings screen, pressing back...")
                # Try to toggle the switch if visible
                switch = d(className="android.widget.Switch")
                if switch.exists(timeout=1):
                    switch.click()
                    time.sleep(0.5)
                d.press("back")
                time.sleep(1)
                acted = True
        except Exception:
            pass

        if not acted:
            # Try common permission dialog buttons
            for text in ["Allow", "Grant"]:
                btn = d(text=text)
                if btn.exists(timeout=1):
                    btn.click()
                    acted = True
                    break

        if not acted:
            # Try dismissal buttons
            for text in ["Don't allow", "Deny", "Not now", "Cancel", "OK"]:
                btn = d(text=text)
                if btn.exists(timeout=0.5):
                    btn.click()
                    acted = True
                    break

        if not acted:
            # Try generic dialog button
            btn = d(resourceId="android:id/button1")
            if btn.exists(timeout=0.5):
                btn.click()
                acted = True

        if acted:
            idle_rounds = 0
            time.sleep(0.7)
        else:
            idle_rounds += 1
            time.sleep(0.5)


def main():
    parser = argparse.ArgumentParser(description="Gotify login automation")
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    # Parse port from server URL
    parsed = urlparse(args.server_url)
    port = parsed.port or 8080

    setup_adb_forwarding(port)

    # Use localhost via ADB forwarding
    server_url = f"http://127.0.0.1:{port}"
    log(f"Using ADB-forwarded URL: {server_url}")

    d = initialize_ui_automation()
    _setup_anr_watcher(d)

    # Launch app
    log("Launching Gotify app...")
    d.app_start(PACKAGE, wait=True, use_monkey=True)
    time.sleep(2)
    wait_for_ui_stable(d, timeout=10)

    result = ensure_logged_in(d, server_url, args.username, args.password)
    sys.exit(result)


if __name__ == "__main__":
    main()
