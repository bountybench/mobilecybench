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


def reset_app_task(d, package_name):
    """Reset Jerboa's foreground task without wiping app-private files/state."""
    d.shell(f"am force-stop {package_name}")
    time.sleep(1)


def wait_for_entry_state(d, timeout=30):
    """
    Wait for a real interactive Jerboa entry state after launch.

    The Compose splash screen is stable enough to satisfy hierarchy-dump checks,
    but it is not actionable. Jerboa then routes to Home, where automation can
    see a changelog dialog (`Done`) or the home drawer icon (`Menu`). We also
    accept landing directly on the login form if the UI stack is already there.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if d(text="Done").exists:
            return "done"
        if d(description="Menu").exists:
            return "menu"
        if d(text="Login").exists and d(textContains="assword").exists:
            return "login"
        if d(description="Logo").exists:
            time.sleep(0.5)
            continue
        time.sleep(0.5)
    return None


def open_add_account_mode(d):
    """
    Open Jerboa's drawer add-account mode.

    Codebase contract:
    - anonymous state exposes "Anonymous", which toggles add-account mode
    - logged-in drawer state renders a full-width clickable DrawerHeader above
      the first main drawer item; tapping that header toggles add-account mode
    """
    add_account = d(text="Add Account")
    if not add_account.exists:
        add_account = d(text="Add account")
    if add_account.exists:
        return add_account

    anonymous = d(text="Anonymous")
    if anonymous.exists:
        if click_then_expect(d, anonymous, add_account, timeout=10):
            return add_account
        return None

    for drawer_item_text in (
        "Subscribed",
        "Local",
        "All",
        "Profile",
        "Inbox",
        "Settings",
    ):
        drawer_item = d(text=drawer_item_text)
        if not drawer_item.exists:
            continue
        bounds = drawer_item.info.get("bounds", {})
        top = bounds.get("top")
        left = bounds.get("left")
        right = bounds.get("right")
        if top is None or left is None or right is None:
            continue
        # DrawerHeader is a full-width clickable box directly above the first
        # main drawer item in Home.kt, so tapping midway between screen top and
        # that first item opens add-account mode without relying on account-name
        # text that Jerboa does not render as a drawer action.
        x = (left + right) // 2
        y = max(48, top // 2)
        d.click(x, y)
        if add_account.wait(timeout=5):
            return add_account
        break

    return None


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

    reset_app_task(d, package_name)

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

    # --- Resolve the first actionable state ---
    done_button = d(text="Done")
    menu_icon = d(description="Menu")
    entry_state = wait_for_entry_state(d, timeout=20)
    if entry_state == "done":
        log("Dismissing changelog...")
        if not click_then_expect(d, done_button, menu_icon, timeout=10):
            log("Error: Failed to dismiss changelog")
            return False
    elif entry_state == "menu":
        pass
    elif entry_state == "login":
        menu_icon = None
    else:
        log("Error: Menu icon not found")
        return False

    # --- Navigate to the login form when starting from Home ---
    if menu_icon is not None:
        anonymous = d(text="Anonymous")
        if not click_then_expect(
            d,
            menu_icon,
            lambda: anonymous.exists
            or d(text="Add Account").exists
            or d(text="Add account").exists
            or d(text="Local").exists
            or d(text="All").exists
            or d(text="Profile").exists,
            timeout=10,
        ):
            log("Error: Menu click failed or drawer did not open")
            return False

        add_account = open_add_account_mode(d)
        if add_account is None:
            log("Error: Drawer opened but 'Add Account' could not be reached")
            return False
        log("Clicking 'Add Account'...")
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
