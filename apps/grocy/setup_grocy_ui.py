#!/usr/bin/env python3
"""
Automates Grocy Android initial setup:
1. Clicks through welcome screens
2. Configures server URL
3. Logs in with credentials
"""
import argparse
import sys
import time

import uiautomator2 as u2

parser = argparse.ArgumentParser(description="Grocy Android UI setup automation")
parser.add_argument("--server-url", required=True, help="Grocy server URL")
parser.add_argument("--api-key", required=True, help="Grocy API key")
args = parser.parse_args()

server_url = args.server_url
api_key = args.api_key

d = u2.connect()


def wait_for_ui_stable(timeout=60, interval=0.5):
    """
    Wait until the UI hierarchy stops changing.
    """
    print("Waiting for UI to stabilize...", file=sys.stderr)
    prev_hierarchy = None
    start = time.time()

    while time.time() - start < timeout:
        current_hierarchy = d.dump_hierarchy(compressed=True)
        if current_hierarchy == prev_hierarchy:
            print("UI stabilized", file=sys.stderr)
            return True
        prev_hierarchy = current_hierarchy
        time.sleep(interval)
    print("WARNING: UI did not stabilize within timeout", file=sys.stderr)
    return False


def wait_and_click_text(text, timeout=60):
    """Wait for text to appear and click it."""
    print(f"Looking for text: '{text}'", file=sys.stderr)
    if d(text=text).wait(timeout=timeout):
        print(f"Found and clicking: '{text}'", file=sys.stderr)
        d(text=text).click_exists(timeout=3)
        wait_for_ui_stable(timeout=10)
        return True
    else:
        print(
            f"[ERROR] Could not find text: '{text}' within {timeout}s", file=sys.stderr
        )
        print(d.dump_hierarchy(), file=sys.stderr)
        return False


def wait_and_click_desc(desc, timeout=60):
    """Wait for description to appear and click it."""
    print(f"Looking for description: '{desc}'", file=sys.stderr)
    if d(description=desc).wait(timeout=timeout):
        print(f"Found and clicking description: '{desc}'", file=sys.stderr)
        d(description=desc).click_exists(timeout=3)
        wait_for_ui_stable(timeout=10)
        return True
    else:
        print(
            f"[ERROR] Could not find description: '{desc}' within {timeout}s",
            file=sys.stderr,
        )
        print(d.dump_hierarchy(), file=sys.stderr)
        return False


def wait_and_click_resource_id(resource_id, timeout=60):
    """Wait for resource ID to appear and click it."""
    print(f"Looking for resource ID: '{resource_id}'", file=sys.stderr)
    if d(resourceId=resource_id).wait(timeout=timeout):
        print(f"Found and clicking resource ID: '{resource_id}'", file=sys.stderr)
        d(resourceId=resource_id).click_exists(timeout=3)
        wait_for_ui_stable(timeout=10)
        return True
    else:
        print(
            f"[ERROR] Could not find resource ID: '{resource_id}' within {timeout}s",
            file=sys.stderr,
        )
        print(d.dump_hierarchy(), file=sys.stderr)
        return False


def set_text_by_resource_id(resource_id, text, timeout=30):
    """Set text in a field identified by resource ID."""
    print(f"Setting text in resource ID: '{resource_id}'", file=sys.stderr)
    if d(resourceId=resource_id).wait(timeout=timeout):
        d(resourceId=resource_id).set_text(text)
        print(f"Text set successfully in '{resource_id}'", file=sys.stderr)
        time.sleep(0.5)
        return True
    else:
        print(
            f"[ERROR] Could not find resource ID: '{resource_id}' within {timeout}s",
            file=sys.stderr,
        )
        return False


# Main automation flow
print("Starting Grocy Android UI automation", file=sys.stderr)

# Wait for app to load
wait_for_ui_stable(timeout=120, interval=1)

# Handle welcome/intro screens
# Look for common patterns: "Get started", "Next", "Skip", "Continue"
# Try multiple possible texts
for welcome_text in ["Get started", "START", "Next", "Continue", "Let's start"]:
    if d(textContains=welcome_text).exists or d(text=welcome_text).exists:
        print(f"Found welcome screen with text: '{welcome_text}'", file=sys.stderr)
        wait_and_click_text(welcome_text, timeout=5)
        break

# Look for "Skip" button if there's a tutorial
if d(text="Skip").exists or d(textContains="Skip").exists:
    print("Found Skip button", file=sys.stderr)
    wait_and_click_text("Skip", timeout=5)

# Look for demo/server setup screen
# The welcome screen shows "Demo server" and "Own server" buttons
wait_for_ui_stable(timeout=10)

# Click "Own server" to proceed to server configuration
if d(text="Own server").exists or d(textContains="Own server").exists:
    print("Found 'Own server' button", file=sys.stderr)
    wait_and_click_text("Own server", timeout=5)

# Handle permission dialogs (camera, etc.)
# Look for permission buttons and click "While using the app" or "Only this time"
# Note: Text can be in different cases depending on Android version
wait_for_ui_stable(timeout=5)
for permission_text in [
    "While using the app",
    "WHILE USING THE APP",
    "Only this time",
    "ONLY THIS TIME",
    "Allow",
    "ALLOW",
]:
    if d(text=permission_text).exists:
        print(f"Found permission button: '{permission_text}'", file=sys.stderr)
        wait_and_click_text(permission_text, timeout=5)
        break

# Handle camera error dialog if it appears
# The emulator may not support camera, causing a "Barcode Scanner" error dialog
wait_for_ui_stable(timeout=5)
if (
    d(text="Barcode Scanner").exists
    or d(textContains="camera encountered a problem").exists
):
    print("Found camera error dialog, dismissing...", file=sys.stderr)
    # Click OK button to dismiss the error dialog
    if d(resourceId="android:id/button1").exists:
        d(resourceId="android:id/button1").click()
        print("Dismissed camera error dialog", file=sys.stderr)
        time.sleep(1)

# After permission, Grocy shows QR code scanner
# Click "Enter data manually" to access manual configuration
wait_for_ui_stable(timeout=5)
if d(text="Enter data manually").exists or d(textContains="manually").exists:
    print("Found 'Enter data manually' button", file=sys.stderr)
    wait_and_click_text("Enter data manually", timeout=5)

# Wait longer for login form to fully load
wait_for_ui_stable(timeout=15)
print("Waiting for login form to load...", file=sys.stderr)

# Verify the login form has loaded by checking for key elements
form_loaded = False
for attempt in range(10):
    if (
        d(resourceId="xyz.zedler.patrick.grocy.debug:id/radio_button_http").exists
        or d(resourceId="xyz.zedler.patrick.grocy.debug:id/server_url").exists
    ):
        form_loaded = True
        print("Login form loaded successfully", file=sys.stderr)
        break
    print(f"Waiting for login form... attempt {attempt + 1}/10", file=sys.stderr)
    time.sleep(2)

if not form_loaded:
    print("[ERROR] Login form did not load", file=sys.stderr)
    print(d.dump_hierarchy(), file=sys.stderr)
    sys.exit(1)

# On the login screen, select HTTP protocol first
print("Selecting HTTP protocol...", file=sys.stderr)
if d(resourceId="xyz.zedler.patrick.grocy.debug:id/radio_button_http").exists:
    d(resourceId="xyz.zedler.patrick.grocy.debug:id/radio_button_http").click()
    print("HTTP protocol selected", file=sys.stderr)
    time.sleep(0.5)

# Enter server URL with http:// prefix
# Look for URL input field
wait_for_ui_stable(timeout=5)
print(f"Attempting to enter server URL: {server_url}", file=sys.stderr)

# Try using resource ID first (most reliable)
url_entered = False
if d(resourceId="xyz.zedler.patrick.grocy.debug:id/server_url").exists:
    d(resourceId="xyz.zedler.patrick.grocy.debug:id/server_url").set_text(server_url)
    url_entered = True
# Fallback: Look for EditText with hint containing "URL" or "server"
elif d(className="android.widget.EditText", textContains="URL").exists:
    d(className="android.widget.EditText", textContains="URL").set_text(server_url)
    url_entered = True
elif d(className="android.widget.EditText", textContains="server").exists:
    d(className="android.widget.EditText", textContains="server").set_text(server_url)
    url_entered = True
elif d(className="android.widget.EditText", textContains="http").exists:
    d(className="android.widget.EditText", textContains="http").set_text(server_url)
    url_entered = True
# Last resort: Click on any visible EditText and enter URL
elif d(className="android.widget.EditText").exists:
    print("Found generic EditText, attempting to use it", file=sys.stderr)
    d(className="android.widget.EditText").click()
    time.sleep(0.5)
    d.send_keys(server_url)
    url_entered = True

if not url_entered:
    print("[ERROR] Could not find server URL input field", file=sys.stderr)
    print(d.dump_hierarchy(), file=sys.stderr)
    sys.exit(1)

print("Server URL entered successfully", file=sys.stderr)
time.sleep(1)

# Enter API key
print("Attempting to enter API key", file=sys.stderr)

# Try using resource ID first (most reliable)
api_key_entered = False
if d(resourceId="xyz.zedler.patrick.grocy.debug:id/api_key").exists:
    d(resourceId="xyz.zedler.patrick.grocy.debug:id/api_key").set_text(api_key)
    api_key_entered = True
# Fallback: Try to find field by hint/description containing "key" or "API"
elif (
    d(textContains="key").exists
    or d(textContains="Key").exists
    or d(textContains="API").exists
):
    if d(className="android.widget.EditText", textContains="key").exists:
        d(className="android.widget.EditText", textContains="key").set_text(api_key)
        api_key_entered = True
    elif d(className="android.widget.EditText", textContains="Key").exists:
        d(className="android.widget.EditText", textContains="Key").set_text(api_key)
        api_key_entered = True
    elif d(className="android.widget.EditText", textContains="API").exists:
        d(className="android.widget.EditText", textContains="API").set_text(api_key)
        api_key_entered = True
# Last resort: Use any available EditText (should be the API key field)
elif d(className="android.widget.EditText").exists:
    print("Using first available EditText for API key", file=sys.stderr)
    d(className="android.widget.EditText", instance=0).set_text(api_key)
    api_key_entered = True

if not api_key_entered:
    print("[ERROR] Could not find API key input field", file=sys.stderr)
    print(d.dump_hierarchy(), file=sys.stderr)
    sys.exit(1)

print("API key entered successfully", file=sys.stderr)
time.sleep(0.5)

# Dismiss keyboard to ensure Login button is visible
print("Dismissing keyboard...", file=sys.stderr)
d.press("back")
time.sleep(1)

# Submit login - try multiple times with different methods
print("Attempting to login...", file=sys.stderr)
login_success = False
max_attempts = 5

for attempt in range(max_attempts):
    print(f"Login attempt {attempt + 1}/{max_attempts}", file=sys.stderr)

    # Method 1: Click by text
    if d(text="Login").exists:
        print("Clicking Login button (by text)...", file=sys.stderr)
        d(text="Login").click()

        # Wait for UI to stabilize after navigation
        wait_for_ui_stable(timeout=15)

        # Check for positive indicators of successful login on main screen
        if d(text="Stock overview").exists or d(text="Shopping list").exists:
            print("Login successful! Main screen loaded.", file=sys.stderr)
            login_success = True
            break

        # Alternative check: Login button should be gone
        if not d(text="Login").exists:
            print("Login successful! Login screen dismissed.", file=sys.stderr)
            login_success = True
            break

        # Still on login screen
        print(
            f"Still on login screen after attempt {attempt + 1}, trying again...",
            file=sys.stderr,
        )
        time.sleep(2)

    # Method 2: Try clicking button element directly
    if not login_success and d(className="android.widget.Button", text="Login").exists:
        print("Clicking Login button (by className)...", file=sys.stderr)
        d(className="android.widget.Button", text="Login").click()

        # Wait for UI to stabilize after navigation
        wait_for_ui_stable(timeout=15)

        # Check for positive indicators of successful login
        if d(text="Stock overview").exists or d(text="Shopping list").exists:
            print("Login successful! Main screen loaded.", file=sys.stderr)
            login_success = True
            break

        # Alternative check: Login button should be gone
        if not d(text="Login").exists:
            print("Login successful! Login screen dismissed.", file=sys.stderr)
            login_success = True
            break

if not login_success:
    print("WARNING: Login may not have completed successfully", file=sys.stderr)
else:
    print("Login completed successfully", file=sys.stderr)

# Wait for UI to stabilize
wait_for_ui_stable(timeout=10)

print("Grocy Android UI automation completed", file=sys.stderr)
