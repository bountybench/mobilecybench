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
SERVER_URL = "http://10.0.2.2:8000"


def parse_args():
    parser = argparse.ArgumentParser(description="Moodle App Login Automation")
    parser.add_argument("--username", required=True, help="Login username")
    parser.add_argument("--password", required=True, help="Login password")
    # Optional arguments to match common interface
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

    print("Connecting to device...")
    d = initialize_ui_automation()

    print(f"Stopping and starting app: {PACKAGE_NAME}")
    d.app_stop(PACKAGE_NAME)
    d.app_start(PACKAGE_NAME)

    # Wait for app to load
    wait_for_ui_stable(d)

    # 1. Allow notifications (if requested)
    print("Checking for notification permission...")
    if d(text="Allow").exists:
        d(text="Allow").click()
        print("Clicked 'Allow' for notifications")
        wait_for_ui_stable(d)
    elif d(
        resourceId="com.android.permissioncontroller:id/permission_allow_button"
    ).exists:
        d(
            resourceId="com.android.permissioncontroller:id/permission_allow_button"
        ).click()
        print("Clicked 'Allow' (ID) for notifications")
        wait_for_ui_stable(d)

    # 2. I'm a learner
    print('Looking for "I\'m a learner" button...')
    learner_btn = d(text="I'm a learner")
    if learner_btn.exists:
        learner_btn.click()
        print('Clicked "I\'m a learner"')
        wait_for_ui_stable(d)

    # 3. Input emulator server
    print(f"Inputting server URL: {SERVER_URL}")
    site_input = d(className="android.widget.EditText")
    if not site_input.exists:
        # Try to find by text or description if generic class fails
        site_input = d(textContains="Your site")

    if site_input.exists:
        site_input.set_text(SERVER_URL)
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
            # Notification popup appeared — dismiss it, but verify login below.
            print("Notification popup visible; dismissing before confirming login...")
            try:
                d(text="Turn on").click()
            except Exception:
                pass
            time.sleep(2)

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
                    try:
                        d(text="Turn on").click()
                    except Exception:
                        pass
                    time.sleep(2)
                    if (
                        d(text="Dashboard").exists
                        or d(text="Site home").exists
                        or d(text="Home").exists
                    ):
                        print("Login confirmed after dismissing notification popup.")
                        login_successful = True
                        break

                print("Not yet on Dashboard/Home...")

        # Handle Post-Login Popups
        if login_successful or d(textContains="Turn on").exists:
            print("Handling post-login popups...")

            # 1. Real time alerts "Turn on"
            if d(text="Turn on").exists:
                print("Found 'Turn on' notifications popup. Clicking...")
                d(text="Turn on").click()
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
        if (
            d(text="Dashboard").exists
            or d(text="Site home").exists
            or d(text="Home").exists
        ):
            print("Login successful!")
            login_successful = True
        elif d(resourceId="com.moodle.moodlemobile:id/speed_dial").exists:
            print("Login successful! (speed dial found)")
            login_successful = True
        else:
            print(
                "Login check: Dashboard/Site home/speed_dial not found — login failed."
            )
            try:
                print(d.dump_hierarchy())
            except Exception:
                pass
            login_successful = False

        return 0 if login_successful else 1

    else:
        print("Login fields not found.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
