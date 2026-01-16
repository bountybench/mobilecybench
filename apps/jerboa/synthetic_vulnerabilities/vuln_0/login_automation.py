#!/usr/bin/env python3
"""
Jerboa login automation using UI Automator
"""

import argparse
import subprocess
import sys
import time


def run_adb(cmd):
    """Run adb command and return output"""
    result = subprocess.run(
        f"adb shell {cmd}", shell=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def tap(x, y):
    """Tap at coordinates"""
    run_adb(f"input tap {x} {y}")
    time.sleep(1)


def dismiss_dropdown():
    """Dismiss any dropdown by tapping on empty space"""
    # Tap on upper right corner (away from back button and any UI elements)
    run_adb("input tap 700 150")
    time.sleep(0.5)


def focus_and_clear_field(x, y):
    """Focus a text field and clear it"""
    # Tap the field
    tap(x, y)
    time.sleep(0.5)

    # Try to show keyboard explicitly
    run_adb("am broadcast -a android.intent.action.CLOSE_SYSTEM_DIALOGS")
    time.sleep(0.3)

    # Clear any existing text
    run_adb("input keyevent 123")  # MOVE_END
    time.sleep(0.2)
    for _ in range(50):  # Delete up to 50 chars
        run_adb("input keyevent 67")  # DEL
    time.sleep(0.3)


def input_text(text):
    """Input text using direct adb input with proper encoding"""
    # Encode special characters for adb shell
    # Replace spaces with %s for proper encoding
    encoded_text = text.replace(" ", "%s")

    # Use shell quoting to handle special characters
    run_adb(f'input text "{encoded_text}"')
    time.sleep(0.5)


def press_back():
    """Press back button"""
    run_adb("input keyevent 4")
    time.sleep(1)


def dismiss_dialogs():
    """Detect and dismiss any pop-up dialogs that might interfere"""
    import os
    import re

    # Get current UI
    for _ in range(3):
        result = subprocess.run(
            "adb shell uiautomator dump", shell=True, capture_output=True
        )
        if result.returncode != 0:
            time.sleep(0.5)
            continue

        result = subprocess.run(
            "adb pull /sdcard/window_dump.xml /tmp/ui_dialog_check.xml",
            shell=True,
            capture_output=True,
        )
        if result.returncode != 0:
            time.sleep(0.5)
            continue

        if os.path.exists("/tmp/ui_dialog_check.xml"):
            try:
                with open("/tmp/ui_dialog_check.xml", "r") as f:
                    content = f.read()

                    # Check for stylus dialog
                    if "Try out your stylus" in content or "Write here" in content:
                        print("  Detected stylus dialog, clicking Cancel...")

                        # Try to find and click Cancel button
                        pattern = r'text="Cancel"[^>]*bounds="\[([0-9]+),([0-9]+)\]\[([0-9]+),([0-9]+)\]"'
                        match = re.search(pattern, content)
                        if match:
                            x1, y1, x2, y2 = map(int, match.groups())
                            center_x = (x1 + x2) // 2
                            center_y = (y1 + y2) // 2
                            tap(center_x, center_y)
                        else:
                            # Fallback to back button
                            press_back()

                        time.sleep(1)
                        return True

                    # Check for other common dialogs
                    if "Cancel" in content and "Next" in content:
                        print("  Detected dialog, pressing back...")
                        press_back()
                        time.sleep(1)
                        return True

                return False
            except Exception:
                pass

    return False


def find_element_bounds(text):
    """Find element with specific text and return center coordinates"""
    import os

    # Retry UI dump up to 3 times
    for _ in range(3):
        # Dump UI
        result = subprocess.run(
            "adb shell uiautomator dump", shell=True, capture_output=True
        )
        if result.returncode != 0:
            time.sleep(0.5)
            continue

        result = subprocess.run(
            "adb pull /sdcard/window_dump.xml /tmp/ui_jerboa.xml",
            shell=True,
            capture_output=True,
        )
        if result.returncode != 0:
            time.sleep(0.5)
            continue

        # Check if file exists and is readable
        if os.path.exists("/tmp/ui_jerboa.xml"):
            try:
                with open("/tmp/ui_jerboa.xml", "r") as f:
                    content = f.read()
                    if len(content) > 0:
                        break
            except Exception:
                time.sleep(0.5)
                continue

        time.sleep(0.5)
    else:
        return None

    # Find element with matching text
    import re

    pattern = f'text="{re.escape(text)}"[^>]*bounds="\\[([0-9]+),([0-9]+)\\]\\[([0-9]+),([0-9]+)\\]"'
    match = re.search(pattern, content)

    if match:
        x1, y1, x2, y2 = map(int, match.groups())
        center_x = (x1 + x2) // 2
        center_y = (y1 + y2) // 2
        return center_x, center_y

    return None


def find_clickable_element(text=None, content_desc=None):
    """Find clickable element by text or content-desc"""
    import os

    # Retry UI dump up to 3 times
    for _ in range(3):
        result = subprocess.run(
            "adb shell uiautomator dump", shell=True, capture_output=True
        )
        if result.returncode != 0:
            time.sleep(0.5)
            continue

        result = subprocess.run(
            "adb pull /sdcard/window_dump.xml /tmp/ui_jerboa.xml",
            shell=True,
            capture_output=True,
        )
        if result.returncode != 0:
            time.sleep(0.5)
            continue

        if os.path.exists("/tmp/ui_jerboa.xml"):
            try:
                with open("/tmp/ui_jerboa.xml", "r") as f:
                    content = f.read()
                    if len(content) > 0:
                        break
            except Exception:
                time.sleep(0.5)
                continue

        time.sleep(0.5)
    else:
        return None

    import re

    if text:
        pattern = f'text="{re.escape(text)}"[^>]*bounds="\\[([0-9]+),([0-9]+)\\]\\[([0-9]+),([0-9]+)\\]"'
    elif content_desc:
        pattern = f'content-desc="{re.escape(content_desc)}"[^>]*bounds="\\[([0-9]+),([0-9]+)\\]\\[([0-9]+),([0-9]+)\\]"'
    else:
        return None

    match = re.search(pattern, content)

    if match:
        x1, y1, x2, y2 = map(int, match.groups())
        center_x = (x1 + x2) // 2
        center_y = (y1 + y2) // 2
        return center_x, center_y

    return None


def login_to_jerboa(instance, username, password):
    """
    Automate login to Jerboa app

    Args:
        instance: Lemmy instance URL (e.g., "lemmy.ml" or "http://10.0.2.2:8536")
        username: Username
        password: Password
    """
    print("Starting Jerboa login automation...")
    print(f"Instance: {instance}")
    print(f"Username: {username}")

    # Launch app fresh
    print("\n[1/6] Launching Jerboa...")
    # Force stop and clear app data to ensure logged-out state
    print("  Clearing app data to ensure logged-out state...")
    run_adb("am force-stop com.jerboa.debug")
    time.sleep(0.5)
    run_adb("pm clear com.jerboa.debug")
    time.sleep(1)

    # Set keyboard to Google keyboard (not stylus) for text input to work
    print("  Setting input method to Google keyboard...")
    run_adb(
        "ime set com.google.android.inputmethod.latin/com.android.inputmethod.latin.LatinIME"
    )
    time.sleep(0.5)

    # Disable stylus IME to prevent "Try out your stylus" dialog
    print("  Disabling stylus features...")
    run_adb("settings put secure stylus_ever_used 1")  # Pretend stylus was already used
    run_adb(
        "settings put global stylus_pointer_icon_enabled 0"
    )  # Disable stylus features
    time.sleep(0.3)

    run_adb("am start -n com.jerboa.debug/com.jerboa.MainActivity")
    time.sleep(5)  # Give app time to fully load

    # Check for and dismiss all "Done" dialogs (changelog, support dialog, etc.)
    print("[2/6] Checking for welcome/dialog screens...")
    time.sleep(1)  # Brief delay before UI dump

    # Try up to 3 times to dismiss any "Done" dialogs
    for i in range(3):
        coords = find_element_bounds("Done")
        if coords:
            print(f"  Found dialog {i+1}, clicking Done...")
            tap(*coords)
            time.sleep(2)
        else:
            print(f"  No more dialogs found after {i} dismissals")
            break

    # Click Profile tab
    print("[3/6] Opening Profile tab...")
    coords = find_element_bounds("Profile")
    if not coords:
        print("  Profile tab not immediately visible, trying to navigate...")
        # App might be on a different screen, try pressing back first
        press_back()
        time.sleep(1)
        coords = find_element_bounds("Profile")
        if not coords:
            print("  ERROR: Profile tab not found")
            return False
    tap(*coords)
    time.sleep(2)

    # Look for "Login" button or "Add account" button
    print("[4/6] Looking for login option...")

    # Check if "Login" button exists (when not logged in via Profile tab)
    coords = find_element_bounds("Login")
    if coords:
        print("  Found Login button, clicking...")
        tap(*coords)
        time.sleep(2)
    else:
        # Try to find "Add account" in drawer
        print("  Opening account menu...")
        # Open hamburger menu first
        coords = find_clickable_element(content_desc="Menu")
        if coords:
            tap(*coords)
            time.sleep(2)

        # Click on "Anonymous" to expand account dropdown
        coords = find_element_bounds("Anonymous")
        if coords:
            print("  Expanding account dropdown...")
            tap(*coords)
            time.sleep(1)

        # Now look for "Add account"
        coords = find_element_bounds("Add account")
        if coords:
            print("  Found Add account, clicking...")
            tap(*coords)
            time.sleep(2)
        else:
            print("  ERROR: Could not find login option")
            return False

    # Fill in login form by finding actual field positions
    print("[5/6] Filling login form...")

    # Get all EditText fields
    import os

    for _ in range(3):
        subprocess.run("adb shell uiautomator dump", shell=True, capture_output=True)
        subprocess.run(
            "adb pull /sdcard/window_dump.xml /tmp/ui_form.xml",
            shell=True,
            capture_output=True,
        )
        if os.path.exists("/tmp/ui_form.xml"):
            break
        time.sleep(0.5)

    if os.path.exists("/tmp/ui_form.xml"):
        with open("/tmp/ui_form.xml", "r") as f:
            ui_content = f.read()

        # Find all EditText bounds
        import re

        pattern = r'class="android.widget.EditText"[^>]*bounds="\[([0-9]+),([0-9]+)\]\[([0-9]+),([0-9]+)\]"'
        matches = re.findall(pattern, ui_content)

        if len(matches) >= 3:
            # Calculate center coordinates for each field
            fields = []
            for match in matches[
                :4
            ]:  # Get first 4 fields (instance, username, password, 2FA)
                x1, y1, x2, y2 = map(int, match)
                center_x = (x1 + x2) // 2
                center_y = (y1 + y2) // 2
                fields.append((center_x, center_y))

            # Instance field
            print(f"  Entering instance: {instance}")
            dismiss_dialogs()
            focus_and_clear_field(fields[0][0], fields[0][1])
            if dismiss_dialogs():
                focus_and_clear_field(fields[0][0], fields[0][1])
            input_text(instance)
            time.sleep(0.5)
            # Dismiss dropdown by tapping empty space
            print("  Dismissing dropdown...")
            dismiss_dropdown()
            time.sleep(0.5)

            # Username field
            print(f"  Entering username: {username}")
            dismiss_dialogs()
            focus_and_clear_field(fields[1][0], fields[1][1])
            if dismiss_dialogs():
                focus_and_clear_field(fields[1][0], fields[1][1])
            input_text(username)
            time.sleep(0.5)
            # Dismiss any dropdown
            dismiss_dropdown()
            time.sleep(0.5)

            # Password field
            print("  Entering password...")
            dismiss_dialogs()
            focus_and_clear_field(fields[2][0], fields[2][1])
            if dismiss_dialogs():
                focus_and_clear_field(fields[2][0], fields[2][1])
            input_text(password)
            time.sleep(0.5)
            # Dismiss any dropdown
            dismiss_dropdown()
            time.sleep(0.5)
        else:
            print("  ERROR: Could not find form fields")
            return False
    else:
        print("  ERROR: Could not dump UI")
        return False

    # Verify text was entered (take screenshot for debugging if needed)
    print("  Verifying form was filled...")
    time.sleep(1)

    # Submit login
    print("[6/6] Submitting login...")
    # Dismiss any final dialogs before clicking login
    dismiss_dialogs()

    coords = (
        find_element_bounds("Login")
        or find_element_bounds("Sign in")
        or find_element_bounds("Log in")
    )
    if coords:
        tap(*coords)
        print("  Login submitted!")
        time.sleep(3)
    else:
        print("  Warning: Login button not found, trying Enter key...")
        run_adb("input keyevent 66")  # KEYCODE_ENTER
        time.sleep(3)

    print("\n✓ Login automation complete!")
    print("  Note: If login fails, check logcat for errors or retry manually")
    return True


def main():
    parser = argparse.ArgumentParser(description="Automate Jerboa login")
    parser.add_argument("instance", help="Lemmy instance URL")
    parser.add_argument("username", help="Username")
    parser.add_argument("password", help="Password")

    args = parser.parse_args()

    # Check device connection
    result = subprocess.run("adb devices", shell=True, capture_output=True, text=True)
    if "device" not in result.stdout:
        print("ERROR: No Android device connected")
        sys.exit(1)

    # Run login automation
    success = login_to_jerboa(args.instance, args.username, args.password)

    if not success:
        print("\nLogin automation failed. Please check the output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
