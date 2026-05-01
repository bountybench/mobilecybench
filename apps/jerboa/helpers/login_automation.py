#!/usr/bin/env python3
import os
import sys
import time
import traceback

try:
    from apps.jerboa.helpers.ui_session import (
        configure_adb,
        connect_u2,
        get_release_package,
        register_anr_watchers,
        verify_or_recover_u2,
    )
    from utils.ui_utils import click_then_expect, wait_for_ui_stable
except ImportError as e:
    print(
        f"Error: Could not import Jerboa UI helpers: {e}\nMake sure the mobilecybench package is installed"
    )
    sys.exit(1)


def log(msg):
    print(f"[login_automation] {msg}", file=sys.stderr)


# Shell metacharacters that must be escaped for ADB `input text`
_SHELL_ESCAPE = {
    " ": "%s",
    "&": "\\&",
    "|": "\\|",
    ";": "\\;",
    "<": "\\<",
    ">": "\\>",
    "(": "\\(",
    ")": "\\)",
    "$": "\\$",
    "`": "\\`",
    "\\": "\\\\",
    '"': '\\"',
    "'": "\\'",
    "*": "\\*",
    "?": "\\?",
    "[": "\\[",
    "]": "\\]",
    "#": "\\#",
    "~": "\\~",
    "=": "\\=",
    "%": "\\%",
}


def input_text_safe(d, text):
    """Input text via ADB, escaping shell metacharacters."""
    escaped = "".join(_SHELL_ESCAPE.get(c, c) for c in text)
    d.shell(f"input text {escaped}")


def clear_and_type(d, field, text):
    """Click a field, clear its contents, and type new text via ADB."""
    field.click()
    time.sleep(0.5)
    d.shell("input keyevent KEYCODE_MOVE_END")
    for _ in range(50):
        d.shell("input keyevent KEYCODE_DEL")
    time.sleep(0.3)
    input_text_safe(d, text)


def find_field(d, selectors, timeout=2):
    """Poll multiple uiautomator2 selector kwargs until one matches or timeout expires."""
    deadline = time.time() + timeout
    while True:
        for sel in selectors:
            field = d(**sel)
            if field.exists:
                return field
        if time.time() >= deadline:
            return None
        time.sleep(0.5)


def login_jerboa(instance_url, username, password):
    """
    Automate login to the Jerboa app.

    Uses resourceId-based selectors, keyboard dismissal, and screen-change
    verification for robustness on emulators.
    """
    log(f"Starting login — Instance: {instance_url}, Username: {username}")

    # --- Device connection ---
    try:
        configure_adb(log)
        d, device_serial = connect_u2(log)
        d = verify_or_recover_u2(d, device_serial, log)
        if d is None:
            return False

        register_anr_watchers(d, log)

    except Exception as e:
        log(f"Error connecting to device: {e}")
        log(f"ADB_SERVER_SOCKET={os.environ.get('ADB_SERVER_SOCKET', 'not set')}")
        log(traceback.format_exc())
        return False

    # --- Detect and launch app ---
    package_name = get_release_package(d)
    log(f"Using package: {package_name}")

    log("Launching Jerboa...")
    d.shell(f"am start -n {package_name}/com.jerboa.MainActivity")

    for _ in range(10):
        if d.shell(f"pidof {package_name}").output:
            log("App is running")
            break
        time.sleep(0.5)
    else:
        log("Error: App did not start")
        return False

    # Wait for UI stability to prevent System UI ANR
    log("Waiting for UI to stabilize...")
    wait_for_ui_stable(d, min_consecutive=3, retry_delay=1, timeout=30)
    log("UI is stable")

    try:
        d.screenshot("/tmp/jerboa_screen.png")
    except Exception:
        pass

    # --- Dismiss changelog if present ---
    done_button = d(text="Done")
    menu_icon = d(description="Menu")

    if done_button.wait(timeout=5):
        log("Dismissing changelog...")
        if not click_then_expect(d, done_button, menu_icon, timeout=10):
            log("Error: Failed to dismiss changelog")
            return False
    elif not menu_icon.wait(timeout=10):
        log("Error: Menu icon not found")
        return False

    # --- Navigate to Add account ---
    anonymous = d(text="Anonymous")
    if not click_then_expect(d, menu_icon, anonymous, timeout=10):
        log("Error: Menu click failed or 'Anonymous' not found")
        return False

    add_account = d(text="Add account")
    if not click_then_expect(d, anonymous, add_account, timeout=10):
        log("Error: 'Add account' not found")
        return False

    log("Clicking 'Add account'...")
    add_account.click()
    instance_field = find_field(
        d,
        [
            {"text": "Instance"},
            {"textContains": "Instance"},
            {"textContains": "instance"},
            {"className": "android.widget.EditText", "instance": 0},
        ],
        timeout=5,
    )
    if instance_field is None:
        log("Error: Instance field not found")
        return False

    # --- Fill login form ---
    log("Filling instance field...")
    clear_and_type(d, instance_field, instance_url)

    username_field = find_field(
        d,
        [
            {"text": "Email or username"},
            {"textContains": "Email or"},
            {"textContains": "username"},
        ],
        timeout=5,
    )
    if username_field is None:
        log("Error: Username field not found")
        return False
    log("Filling username...")
    clear_and_type(d, username_field, username)

    password_field = find_field(
        d,
        [
            {"text": "Password"},
            {"textContains": "assword"},
        ],
        timeout=5,
    )
    if password_field is None:
        log("Error: Password field not found")
        return False
    log("Filling password...")
    clear_and_type(d, password_field, password)

    # Dismiss keyboard without navigating away (pressing back may exit the form)
    d.press("enter")
    time.sleep(2)

    # --- Click Login ---
    login_button = find_field(
        d,
        [
            {"text": "Login"},
            {"text": "Log in"},
            {"text": "Sign in"},
            {"textContains": "Login"},
        ],
        timeout=15,
    )
    if login_button is None:
        log("Error: Login button not found")
        return False

    try:
        info = login_button.info
        log(
            f"Login button: enabled={info.get('enabled')}, clickable={info.get('clickable')}"
        )
        d.screenshot("/tmp/before_login_click.png")
    except Exception:
        pass

    log("Clicking 'Login'...")

    def login_succeeded():
        # Require BOTH conditions to avoid false positives:
        # - password field gone: login form has closed (not just showing spinner)
        # - username present: logged in successfully (not an error state)
        # d(text="Local") and d(text=username) both exist while the spinner is
        # showing because the form fields are still on screen. Checking that the
        # password field is gone ensures the form has actually been dismissed.
        try:
            password_gone = not d(textContains="assword").exists
            username_present = d(text=username).exists
            return password_gone and username_present
        except Exception:
            return False

    # --- Verify login ---
    try:
        if click_then_expect(d, login_button, login_succeeded, timeout=30):
            log("✓ Login successful!")
            if d(text="Anonymous").exists:
                log("Closing drawer after login...")
                d.press("back")
                time.sleep(1)
            return True
    except Exception as e:
        log(f"Warning: click_then_expect failed: {e}")

    log("Error: Login did not complete — username not found in UI after login click")
    return False


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: login_automation.py <instance_url> <username> <password>")
        sys.exit(1)

    success = login_jerboa(sys.argv[1], sys.argv[2], sys.argv[3])
    sys.exit(0 if success else 1)
