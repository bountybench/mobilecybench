#!/usr/bin/env python3

import argparse
import sys
import time

import uiautomator2 as u2


def main():
    parser = argparse.ArgumentParser(description="DAVx5 simple login")
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    d = u2.connect()

    def log(msg):
        if args.verbose:
            print(f"[DAVx5] {msg}", file=sys.stderr)

    def wait_ui_stable(timeout=1):
        time.sleep(timeout)

    # Starting the app
    d.app_start("at.bitfire.davdroid")
    wait_ui_stable()

    # There are 4 pages of onboarding when the app starts
    # Normally there are 5 (one is permissions), but since we installed the apk with
    # -g it has all permissions and skips that page
    log("Handling onboarding")
    for i in range(4):
        d(description="Next").click()
        wait_ui_stable()

    # In the main screen you must click "Add account"
    # to begin the login process
    log("Clicking Add account")
    d(description="Add account").click()
    wait_ui_stable()

    # Different types of login exist, we just want
    # the first option
    log("Selecting login option and continuing")
    d(checkable=True).click()  # click first option
    wait_ui_stable()
    d(text="Continue").click()  # move on
    wait_ui_stable()

    # The actual login page has 3 fields, server, username, and password
    # we fill in the server url first
    log("Filling server URL")
    edit_texts = d(className="android.widget.EditText")
    edit_texts.click()
    wait_ui_stable()
    edit_texts.set_text(args.server_url)
    d.press("enter")
    wait_ui_stable()

    # Next we fill in the username
    log("Filling username")
    edit_texts = d(className="android.widget.EditText")
    edit_texts[1].click()
    wait_ui_stable()
    edit_texts[1].set_text(args.username)
    d.press("enter")
    wait_ui_stable()

    # finally the password
    log("Filling password")
    edit_texts = d(className="android.widget.EditText")
    edit_texts[2].click()
    wait_ui_stable()
    edit_texts[2].set_text(args.password)

    # Hit the login button
    log("Submitting login")
    d(text="Login").click()
    wait_ui_stable()

    # Final page navigation
    log("Selecting 'Groups are per-contact categories' option")
    radio_buttons = d(className="android.widget.RadioButton")
    radio_buttons[1].click()
    wait_ui_stable()

    # Press the finish button
    log("Clicking finish button")
    d(text="Finish").click()
    wait_ui_stable()

    # Check for success (very rough check)
    hierarchy = d.dump_hierarchy()
    if any(
        word in hierarchy.lower()
        for word in ["success", "connected", "account", "calendar", "contact"]
    ):
        log("✅ Login appears successful")
        return True
    else:
        log("❌ Login may have failed")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
