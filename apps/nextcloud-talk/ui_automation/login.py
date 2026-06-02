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
"""

import argparse
import json
import os
import re
import sys
import time

import uiautomator2 as u2

from utils.ui_utils import click_then_expect

SCRIPT_NAME = "nc_login"
PACKAGE = "com.nextcloud.talk2"
BROWSER_PACKAGE = "com.android.chrome"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
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
    try:
        return d.app_current().get("package", "")
    except Exception:
        return ""


def shell_text(result):
    if hasattr(result, "output"):
        return result.output or ""
    if isinstance(result, str):
        return result
    return str(result)


def log_ui_state(d):
    try:
        app_state = d.app_current()
    except Exception as exc:
        log(f"Current UI unavailable: {exc}")
        return

    snippets = []
    try:
        hierarchy = d.dump_hierarchy(compressed=True)
        for text in re.findall(r'text="([^"]{1,80})"', hierarchy):
            if text and text not in snippets:
                snippets.append(text)
            if len(snippets) >= 8:
                break
    except Exception as exc:
        snippets.append(f"<hierarchy unavailable: {exc}>")

    log(
        "Current UI: "
        f"package={app_state.get('package', '')} "
        f"activity={app_state.get('activity', '')} "
        f"texts={snippets}"
    )


def log_recent_logcat(d):
    try:
        output = shell_text(d.shell("logcat -d -t 200"))
    except Exception as exc:
        log(f"Recent logcat unavailable: {exc}")
        return

    markers = (
        PACKAGE,
        "AndroidRuntime",
        "FATAL EXCEPTION",
        "ActivityTaskManager",
        "ActivityManager",
        "am_crash",
    )
    interesting = [
        line
        for line in output.splitlines()
        if any(marker in line for marker in markers)
    ]
    for line in interesting[-40:]:
        log(f"logcat: {line[:300]}")


def parse_args():
    parser = argparse.ArgumentParser(description="Nextcloud Talk login automation")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--server-url", default=get_default_server_url())
    return parser.parse_args()


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


def server_url_field(d):
    by_id = d(resourceId=f"{PACKAGE}:id/serverEntryTextInputEditText")
    if by_id.exists:
        return by_id

    # Resource IDs are brittle under APK obfuscation and across UI revisions.
    # Fall back to the visible server-address prompt plus the active EditText.
    if current_package(d) != PACKAGE:
        return None
    if not (
        d(textContains="Server address").exists
        or d(textContains="https://").exists
        or d(textContains="server").exists
    ):
        return None

    edit_text = d(className="android.widget.EditText")
    if edit_text.exists:
        return edit_text
    return None


def on_server_url_screen(d):
    return server_url_field(d) is not None


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
        try:
            if condition():
                return True
        except Exception as exc:
            log(f"Condition check failed while waiting: {exc}")
        time.sleep(interval)
    return False


def wait_for_foreground(d, timeout=5, accept_browser=True):
    def foreground_ready():
        package = current_package(d)
        return package == PACKAGE or (accept_browser and package == BROWSER_PACKAGE)

    return wait_for_condition(foreground_ready, timeout=timeout, interval=1)


def launch_app(d, timeout=45, accept_browser=True):
    """Bring Nextcloud Talk to the foreground.

    uiautomator2's app_start can return while the launcher remains foreground
    on slower CI emulators. Retrying with monkey matches start_runtime.sh and
    gives the launcher a second route to the app's MAIN activity.
    """
    deadline = time.time() + timeout
    attempt = 0

    while time.time() < deadline:
        attempt += 1
        try:
            d.app_start(PACKAGE, wait=True)
        except Exception as exc:
            log(f"app_start attempt {attempt} failed: {exc}")
        time.sleep(3)

        if wait_for_foreground(d, timeout=1, accept_browser=accept_browser):
            return True

        try:
            d.shell(f"monkey -p {PACKAGE} -c android.intent.category.LAUNCHER 1")
        except Exception as exc:
            log(f"monkey launch attempt {attempt} failed: {exc}")
        time.sleep(3)

        if wait_for_foreground(d, timeout=1, accept_browser=accept_browser):
            return True

    log("ERROR: Nextcloud Talk did not come to foreground after launch attempts")
    log_ui_state(d)
    log_recent_logcat(d)
    return False


def wait_for_initial_login_state(d, timeout=60, interval=1):
    log("Waiting for initial login state")
    start = time.time()
    while time.time() - start < timeout:
        if is_logged_in(d):
            return "logged_in"
        if on_server_url_screen(d):
            return "server_url"
        if on_ssl_cert_dialog(d):
            return "ssl_cert"
        if current_package(d) == BROWSER_PACKAGE or on_browser_login_handoff_screen(d):
            return "browser"
        time.sleep(interval)

    log("ERROR: Initial login screen did not become ready")
    log_ui_state(d)
    sys.exit(1)


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


def submit_server_url(d, timeout=30):
    def expected():
        return (
            current_package(d) == BROWSER_PACKAGE
            or on_browser_login_handoff_screen(d)
            or on_ssl_cert_dialog(d)
        )

    arrow = d(resourceId=f"{PACKAGE}:id/text_input_end_icon")
    if arrow.exists:
        return click_then_expect(d, arrow, expected, timeout=timeout)

    log("Server URL submit icon not found; submitting with keyboard action")
    d.press("enter")
    return wait_for_condition(expected, timeout=timeout)


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
    server_field = server_url_field(d)
    if server_field is None:
        log("ERROR: Server URL field is not visible")
        log_ui_state(d)
        sys.exit(1)

    server_field.set_text(server_url)
    time.sleep(0.5)

    if not submit_server_url(d, timeout=30):
        log("ERROR: Browser handoff did not start after submitting server URL")
        log_ui_state(d)
        sys.exit(1)

    # Accept self-signed certificate if prompted
    if on_ssl_cert_dialog(d):
        log("Accepting SSL certificate")
        d(resourceId="android:id/button1", text="Yes").click()
        time.sleep(2)
        # After accepting, the app retries the connection — tap arrow again
        if on_server_url_screen(d):
            if not submit_server_url(d, timeout=30):
                log("ERROR: Browser handoff did not start after accepting certificate")
                log_ui_state(d)
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
        d,
        grant_btn,
        lambda: on_account_connected_page(d) or current_package(d) == PACKAGE,
        timeout=30,
    ):
        log("ERROR: Account connected page did not appear after granting access")
        log_ui_state(d)
        sys.exit(1)

    log("Access granted, returning to app")
    if current_package(d) != PACKAGE and not launch_app(
        d, timeout=45, accept_browser=False
    ):
        sys.exit(1)

    if not wait_for_condition(lambda: is_logged_in(d), timeout=45):
        log("ERROR: Main screen not reached after returning to app")
        log_ui_state(d)
        sys.exit(1)
    log("Main screen reached")


def main():
    args = parse_args()

    log(f"Logging in {args.username} on {PACKAGE}")

    d = u2.connect()

    if not launch_app(d):
        sys.exit(1)

    # Already logged in?
    if is_logged_in(d):
        log("Already logged in")
        sys.exit(0)

    # Run login flow
    initial_state = wait_for_initial_login_state(d)
    if initial_state == "logged_in":
        log("Already logged in")
        sys.exit(0)
    if initial_state in {"server_url", "ssl_cert"}:
        handle_server_url(d, args.server_url)

    wait_for_browser(d)
    handle_chrome_first_run(d)
    handle_connect_page(d)
    handle_login_form(d, args.username, args.password)
    handle_grant_access(d)

    log("SUCCESS: Login complete")


if __name__ == "__main__":
    main()
