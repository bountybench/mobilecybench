#!/usr/bin/env python3
import argparse
import os
import sys
import time

# Add project root to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), "../../../"))
from utils.ui_utils import (
    initialize_ui_automation,
    wait_for_ui_stable,
)

PACKAGE_NAME = "com.moodle.moodlemobile"
DEFAULT_SERVER_URL = "http://10.0.2.2:8000"


def dismiss_notification_prompt(d):
    """Dismiss Moodle's in-app notification prompt without leaving login flow."""
    for text in ("Not now", "Maybe later", "Skip"):
        btn = d(text=text)
        if btn.exists:
            print(f"Notification prompt visible; clicking '{text}'")
            btn.click()
            time.sleep(2)
            return True
    if d(textContains="Turn on").exists:
        print("Notification prompt visible; no dismiss button found")
        return True
    return False


def current_package(d):
    try:
        return d.app_current().get("package", "")
    except Exception:
        return ""


def bring_moodle_foreground(d):
    if current_package(d) != PACKAGE_NAME:
        d.app_start(PACKAGE_NAME)
        time.sleep(3)


def wait_for_any(d, selectors, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        bring_moodle_foreground(d)
        for selector in selectors:
            obj = d(**selector)
            if obj.exists:
                return obj
        time.sleep(1)
    return None


def choose_persona(d, username):
    # teacher2 should use the educator onboarding path; janedoe uses learner.
    label = "I'm an educator" if username == "teacher2" else "I'm a learner"
    print(f'Looking for "{label}" button...')
    persona_btn = wait_for_any(
        d,
        [
            {"text": label},
            {"textContains": "educator" if username == "teacher2" else "learner"},
        ],
        timeout=30,
    )
    if persona_btn is None:
        print("Persona screen not found; continuing in case app already advanced")
        return False
    persona_btn.click()
    print(f'Clicked "{label}"')
    wait_for_ui_stable(d)
    return True


def choose_existing_site_if_needed(d):
    existing_site = wait_for_any(
        d,
        [
            {"text": "I already have a Moodle site"},
            {"textContains": "already have a Moodle site"},
        ],
        timeout=8,
    )
    if existing_site is None:
        return False
    existing_site.click()
    print('Clicked "I already have a Moodle site"')
    wait_for_ui_stable(d)
    return True


def _sh_quote(s):
    """Quote a value for `adb shell input text`.

    `adb shell input text` does not handle spaces or shell metacharacters
    reliably across emulator images, so we reject them outright. Moodle
    usernames and the per-run teacher2 password (token_urlsafe → [A-Za-z0-9_-])
    never contain these, so this is a hard guard, not a limitation in
    practice.
    """
    if any(c in s for c in " '\"\\`$&|;<>()"):
        raise ValueError(f"unsupported character in adb input value: {s!r}")
    return s


def logged_in(d):
    """Authoritative logged-in oracle (rendered Ionic dashboard / speed dial).

    Moodle Mobile is a Cordova/Ionic app, so even the dashboard lives inside a
    WebView; but its rendered text labels ("Dashboard", "Site home", "Home")
    and the speed_dial FAB resourceId DO surface to uiautomator2. Only the
    login form's HTML <input> fields are opaque — which is exactly what
    login_via_webview works around. "Turn on" notification prompts are NOT
    counted here: Android can show them before the server response arrives, so
    counting one would false-positive a wrong password.
    """
    return (
        d(text="Dashboard").exists
        or d(text="Site home").exists
        or d(text="Home").exists
        or d(resourceId="com.moodle.moodlemobile:id/speed_dial").exists
    )


def login_via_webview(d, username, password):
    """Enter credentials into Moodle's WebView login form via ADB input.

    Moodle Mobile is a Cordova/Ionic app: after `pm clear` + a cold launch,
    the credentials page (core-login-credentials) renders as HTML inside an
    `android.webkit.WebView`. Its <input> DOM is opaque to uiautomator2, so
    `d(text="Username")`, `d(className="android.widget.EditText")` and the
    native "Log in" button never resolve — every native selector times out and
    the login fails, which makes prepare_victim.sh fatal with
    infrastructure_error.

    Mirroring apps/home-assistant-android/prepare_victim.py:_login_via_webview,
    we drive the form positionally instead of by widget visibility:
      - tap the upper input region to focus the (first) username field,
      - `adb input text <username>`,
      - KEYCODE_TAB → password field,
      - `adb input text <password>`,
      - KEYCODE_ENTER → submit.

    The HTML form's tab order is username → password → submit, so TAB+ENTER
    submits without needing to locate the button. The success oracle is the
    rendered dashboard (logged_in), polled with growing slack to absorb both
    slow JS focus-handler attach and slow post-submit navigation. (The whole
    app is a WebView, so "WebView disappeared" is not a usable signal — the
    rendered dashboard text is.)
    """
    w = d.info["displayWidth"]
    h = d.info["displayHeight"]
    for attempt in range(1, 4):
        # JS in the WebView may not have attached focus handlers yet on a
        # slow emulator; wait longer each attempt before typing (4s, 8s, 12s).
        time.sleep(4 * attempt)
        # Tap the upper-middle of the form to focus the first input. The
        # Moodle credentials form places username above password, both in the
        # top half of the viewport below the site banner.
        d.click(w // 2, int(h * 0.42))
        time.sleep(0.5)
        d.shell(f"input text {_sh_quote(username)}")
        time.sleep(0.3)
        d.shell("input keyevent 61")  # KEYCODE_TAB → password field
        time.sleep(0.3)
        d.shell(f"input text {_sh_quote(password)}")
        time.sleep(0.3)
        d.shell("input keyevent 66")  # KEYCODE_ENTER → submit
        # Poll for the dashboard to paint after the server round-trip. A
        # "Turn on" notification prompt can appear first; dismiss it and keep
        # polling rather than treating it as success or failure.
        deadline = time.time() + 25
        while time.time() < deadline:
            if logged_in(d):
                print(f"WebView login succeeded on attempt {attempt}/3")
                return True
            if d(textContains="Turn on").exists:
                dismiss_notification_prompt(d)
            time.sleep(2)
        print(f"WebView login attempt {attempt}/3 did not reach dashboard; retrying")
        bring_moodle_foreground(d)
    print("WebView login: never reached dashboard after 3 attempts")
    return False


def finalize_login(d):
    """Drain post-login popups and resolve the logged-in oracle authoritatively.

    Shared tail for both the native-widget and WebView credential paths.
    Returns 0 if the app reached a logged-in dashboard, 1 otherwise.
    """
    # Handle Post-Login Popups
    if logged_in(d) or d(textContains="Turn on").exists:
        print("Handling post-login popups...")

        # 1. Real time alerts "Turn on"
        if d(textContains="Turn on").exists:
            dismiss_notification_prompt(d)
            wait_for_ui_stable(d)

        # 2. "Got it" orange buttons (User Tour / Onboarding)
        # We loop until no "Got it" buttons are found.
        max_got_it_clicks = 5
        for _ in range(max_got_it_clicks):
            got_it_btn = d(text="Got it")
            if got_it_btn.exists:
                print("Found 'Got it' button. Clicking...")
                got_it_btn.click()
                time.sleep(1)
                wait_for_ui_stable(d)
            else:
                break

    # Final verification — resolve login_successful authoritatively.
    if logged_in(d):
        print("Login successful!")
        return 0
    else:
        print("Login check: Dashboard/Site home/speed_dial not found — login failed.")
        try:
            print(d.dump_hierarchy())
        except Exception:
            pass
        return 1


def parse_args():
    parser = argparse.ArgumentParser(description="Moodle App Login Automation")
    parser.add_argument("--username", required=True, help="Login username")
    parser.add_argument("--password", required=True, help="Login password")
    # Optional arguments to match common interface
    parser.add_argument(
        "--server-url",
        default=os.environ.get("MOODLE_EMULATOR_SERVER", DEFAULT_SERVER_URL),
        help="Moodle server URL as reachable from the Android emulator",
    )
    parser.add_argument(
        "--user-key", help="Key in secrets.json (ignored if password provided)"
    )
    parser.add_argument(
        "--secrets", help="Path to secrets.json (ignored if password provided)"
    )
    return parser.parse_args()


def main():
    args = parse_args()
    username = args.username
    password = args.password
    server_url = args.server_url

    print("Connecting to device...")
    d = initialize_ui_automation()

    print(f"Stopping and starting app: {PACKAGE_NAME}")
    d.app_stop(PACKAGE_NAME)
    d.app_start(PACKAGE_NAME)
    bring_moodle_foreground(d)

    # Wait for app to load
    wait_for_ui_stable(d)

    # 1. Allow notifications (if requested)
    print("Checking for notification permission...")
    if d(text="Allow").exists:
        d(text="Allow").click()
        print("Clicked 'Allow' for notifications")
        bring_moodle_foreground(d)
        wait_for_ui_stable(d)
    elif d(
        resourceId="com.android.permissioncontroller:id/permission_allow_button"
    ).exists:
        d(
            resourceId="com.android.permissioncontroller:id/permission_allow_button"
        ).click()
        print("Clicked 'Allow' (ID) for notifications")
        bring_moodle_foreground(d)
        wait_for_ui_stable(d)

    # 2. Choose onboarding persona.
    choose_persona(d, username)
    choose_existing_site_if_needed(d)

    # 3. Input emulator server
    print(f"Inputting server URL: {server_url}")
    site_input = wait_for_any(
        d,
        [
            {"className": "android.widget.EditText"},
            {"textContains": "Your site"},
            {"textContains": "site"},
        ],
        timeout=30,
    )
    if site_input is None:
        # Try to find by text or description if generic class fails
        site_input = d(textContains="Your site")

    if site_input is not None and site_input.exists:
        site_input.set_text(server_url)
        print("Set server URL text")

        # Click "Connect to your site" or similar button.
        # Usually it's an arrow or "Connect" or keyboard enter.
        # Let's try to find a confirm button or press enter.
        d.press("enter")
        wait_for_ui_stable(d)

        # Sometimes pressing enter isn't enough, look for a button
        # Or specifically "Connect to your site" if it has text
        if d(text="Connect to your site").exists:
            d(text="Connect to your site").click()
        elif d(description="Connect to your site").exists:
            d(description="Connect to your site").click()

        print("Submitted server URL")
        wait_for_ui_stable(d)
    else:
        print("Could not find site input field")

    # 4. Login with credentials
    print("Waiting for login fields...")
    # Expect username field
    # Moodle Mobile usually shows a webview or native fields.
    # We look for Username and Password fields.

    # WebView-aware fast path. Moodle Mobile is a Cordova/Ionic app and, after
    # `pm clear` + a cold launch, renders the credentials form as HTML inside an
    # android.webkit.WebView whose <input> DOM is opaque to uiautomator2. In
    # that state every native selector below (text="Username", className=
    # EditText, "Log in" Button) times out and the login fails, which makes
    # prepare_victim.sh fatal with infrastructure_error. When no native
    # credential widget is present and we are not already logged in, drive the
    # form positionally via ADB input (mirroring apps/home-assistant-android).
    # Native EditTexts, when present (some app/onboarding states), still take
    # the path below.
    if (
        not logged_in(d)
        and not d(text="Username").exists
        and not d(className="android.widget.EditText").exists
    ):
        # Settle in case we polled mid-transition before the form rendered.
        wait_for_ui_stable(d)
        if (
            not d(text="Username").exists
            and not d(className="android.widget.EditText").exists
        ):
            print("Credentials form is a WebView; driving login via ADB input")
            login_via_webview(d, username, password)
            return finalize_login(d)

    username_field = d(text="Username")
    password_field = d(text="Password")

    if not username_field.exists:
        # Retry waiting or look for alternatives
        wait_for_ui_stable(d)
        # Try generic EditTexts if specific text not found (Moodle often has 2 EditTexts: User, Pass)
        if not username_field.exists:
            print(
                "Standard 'Username' text not found. Checking for resource IDs or hints..."
            )
            username_field = d(resourceIdMatches=".*username.*")
            if not username_field.exists:
                # Check for EditTexts by instance
                edit_texts = d(className="android.widget.EditText")
                if edit_texts.count >= 2:
                    print(
                        "Found generic EditText fields, assuming first is username, second is password."
                    )
                    username_field = edit_texts[0]
                    password_field = edit_texts[1]

    if username_field.exists:
        print(f"Entering username: {username}")
        username_field.set_text(username)
        # Verify text was set? Sometimes set_text fails if field not focused

        time.sleep(1)  # Pause after username

        print("Entering password")
        # specific handling if we found generic fields
        if not password_field.exists and d(text="Password").exists:
            password_field = d(text="Password")

        password_field.click()  # Ensure focus
        password_field.set_text(password)
        time.sleep(1)  # Pause after password

        # User suggestion: Press Enter while focused on password field
        print("Pressing Enter to login...")
        d.press("enter")
        time.sleep(5)

        login_successful = False

        # Check for success immediately after Enter.
        # "Turn on" (notification permission) is NOT a reliable login signal —
        # Android can show it before the server response arrives, so a wrong
        # password would produce a false-success if we count it here.
        if (
            d(text="Dashboard").exists
            or d(text="Site home").exists
            or d(text="Home").exists
        ):
            print("Login successful via Enter key!")
            login_successful = True
        elif d(textContains="Turn on").exists:
            # Notification popup appeared; dismiss it, but verify login below.
            dismiss_notification_prompt(d)

        if not login_successful:
            # If not successful, try clicking the button as backup
            print(
                "Enter key didn't trigger navigation (or confirmed yet). Trying button click..."
            )

            # Now loop click
            max_login_attempts = 3
            for attempt in range(max_login_attempts):
                print(f"Login attempt {attempt + 1}/{max_login_attempts}")

                # Re-check existence - Be specific to BUTTON class to avoid clicking title text
                login_btn = d(text="Log in", className="android.widget.Button")
                if not login_btn.exists:
                    login_btn = d(text="Login", className="android.widget.Button")
                if not login_btn.exists:
                    # Fallback to just text if class specific fails, but warn
                    login_btn = d(text="Log in")
                    if not login_btn.exists:
                        login_btn = d(text="Login")

                if login_btn.exists:
                    print(f"Found '{login_btn.get_text()}' button")
                    try:
                        login_btn.click()
                        print("Clicked button...")
                    except Exception:
                        pass
                else:
                    print("Login button not found by strict text.")
                    # Check if we are back on the "Connect to your site" screen
                    if (
                        d(textContains="Your site").exists
                        or d(text="Connect to your site").exists
                    ):
                        print(
                            "WARNING: We seem to have gone back to Site URL screen. Re-entering URL..."
                        )

                    # Check for buttons again
                    buttons = d(className="android.widget.Button")
                    for b in buttons:
                        try:
                            t = b.info.get("text", "").lower()
                            if "log" in t:
                                b.click()
                                break
                        except Exception:
                            pass

                # Check for success
                time.sleep(5)
                if (
                    d(text="Dashboard").exists
                    or d(text="Site home").exists
                    or d(text="Home").exists
                ):
                    print("Login successful detected!")
                    login_successful = True
                    break

                # "Turn on" notification popup can appear after correct login —
                # dismiss it but do NOT treat its presence alone as proof of success.
                if d(textContains="Turn on").exists:
                    dismiss_notification_prompt(d)
                    if (
                        d(text="Dashboard").exists
                        or d(text="Site home").exists
                        or d(text="Home").exists
                    ):
                        print("Login confirmed after dismissing notification popup.")
                        login_successful = True
                        break

                print("Not yet on Dashboard/Home...")

        # Drain post-login popups and resolve the logged-in oracle.
        return finalize_login(d)

    else:
        # No native credential widget resolved (the form attached late, or the
        # WebView fast path above was skipped by a transient EditText). The form
        # is the opaque Cordova WebView, so drive it via ADB input before giving
        # up — a slow Ionic render must not become an infra failure.
        print("Native credential fields not found; driving WebView login via ADB input")
        login_via_webview(d, username, password)
        return finalize_login(d)


if __name__ == "__main__":
    sys.exit(main())
