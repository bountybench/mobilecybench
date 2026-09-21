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
    return d.app_current().get("package", "")


def dismiss_blocking_dialogs(d):
    """Clear ANR / system dialogs that can sit on top of the app's own UI on
    a slow emulator (e.g. an 'isn't responding' ANR, a launcher/system info
    popup). These block on_server_url_screen() from ever matching. We tap
    'Wait' on ANRs (which keeps the app alive rather than killing it) and
    dismiss benign informational dialogs. Returns True if anything was tapped.
    """
    acted = False
    for _ in range(3):
        # ANR "<app> isn't responding" — Wait keeps the process alive.
        if d(resourceId="android:id/aerr_wait").exists:
            log("ANR dialog present; tapping Wait")
            d(resourceId="android:id/aerr_wait").click()
            time.sleep(2)
            acted = True
            continue
        # Generic system/info dialogs — dismiss without closing the app.
        # Deliberately excludes 'Close app' so we never kill Talk.
        tapped = False
        for label in ("Wait", "OK", "Got it", "Allow"):
            btn = d(text=label, className="android.widget.Button")
            if btn.exists:
                log(f"Dismissing system dialog ({label})")
                btn.click()
                time.sleep(1)
                acted = True
                tapped = True
                break
        if not tapped:
            break
    return acted


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


def wait_for_browser(d, timeout=90):
    """Wait for the app to hand off to the external browser.

    Returns True on success, False if the handoff never appeared (so the
    caller can retry). The handoff races app cold-boot on slow/loaded
    emulators, so the default timeout is generous and failure is non-fatal.
    """
    log("Waiting for external browser")
    if not wait_for_condition(
        lambda: current_package(d) == BROWSER_PACKAGE
        or on_browser_login_handoff_screen(d),
        timeout=timeout,
    ):
        log("Browser login handoff did not appear within timeout")
        return False

    if on_browser_login_handoff_screen(d):
        if not wait_for_condition(
            lambda: current_package(d) == BROWSER_PACKAGE, timeout=timeout
        ):
            log("Chrome did not open after browser handoff screen")
            return False

    log("External browser opened")
    return True


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

    log(f"Logging in {args.username} on {PACKAGE}")

    d = u2.connect()

    # Launch app
    d.app_start(PACKAGE, wait=True)
    time.sleep(3)

    # Already logged in?
    if is_logged_in(d):
        log("Already logged in")
        sys.exit(0)

    # Run login flow. The server-URL screen render and the subsequent
    # browser handoff both race the app's cold boot on a slow/loaded
    # emulator, so retry the whole sequence a few times (relaunching the
    # app between attempts) instead of one-shotting it.
    MAX_ATTEMPTS = 5
    for attempt in range(1, MAX_ATTEMPTS + 1):
        # An ANR/system dialog can cover the app on a slow emulator and stop
        # every screen check below from matching — clear it first.
        dismiss_blocking_dialogs(d)

        if is_logged_in(d):
            log("Already logged in")
            sys.exit(0)

        already_handed_off = current_package(
            d
        ) == BROWSER_PACKAGE or on_browser_login_handoff_screen(d)
        if not already_handed_off:
            # Wait for the server URL screen to actually render before
            # submitting — a one-shot check loses the race on slow boots.
            # Poll dialog-dismissal alongside so an ANR that pops mid-wait
            # doesn't wedge us for the whole timeout.
            def server_screen_ready():
                dismiss_blocking_dialogs(d)
                return on_server_url_screen(d)

            if wait_for_condition(server_screen_ready, timeout=60):
                handle_server_url(d, args.server_url)
            else:
                log(
                    f"Server URL screen not ready (attempt {attempt}/"
                    f"{MAX_ATTEMPTS}; current package={current_package(d)!r}); "
                    "relaunching app"
                )
                d.app_start(PACKAGE, wait=True)
                time.sleep(5)
                continue

        if wait_for_browser(d):
            break

        log(
            f"Browser handoff did not appear (attempt {attempt}/"
            f"{MAX_ATTEMPTS}); relaunching app and retrying"
        )
        d.app_start(PACKAGE, wait=True)
        time.sleep(5)
    else:
        log("ERROR: Browser login handoff did not appear after retries")
        sys.exit(1)

    handle_chrome_first_run(d)
    handle_connect_page(d)
    handle_login_form(d, args.username, args.password)
    handle_grant_access(d)

    log("SUCCESS: Login complete")


if __name__ == "__main__":
    main()
