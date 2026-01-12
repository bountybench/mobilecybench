#!/usr/bin/env python3
"""
Shared utilities for Conversations UI automation scripts.

This module re-exports shared utilities from utils.ui_utils and provides
app-specific helpers for the Conversations XMPP client.
"""
import subprocess
import sys
import time
from datetime import datetime

# Import shared utilities from the central utils module
# These are the preferred functions for click/wait operations
from utils.ui_utils import (
    click_then_expect,
    press_back_then_expect,
    wait_for_screen_change,
)

# Timeout constants (app-specific values)
TIMEOUT_FAST = 5  # For elements that should appear immediately
TIMEOUT_NORMAL = 10  # For typical screen transitions
TIMEOUT_SLOW = 30  # For network operations or first-time setup

# Aliases for backward compatibility with existing code
# New code should use click_then_expect and press_back_then_expect directly
click_and_wait = click_then_expect
press_back_and_wait = press_back_then_expect
_wait_for_screen_change = wait_for_screen_change


def log(message, script_name="ui_automation"):
    """Print log message to stderr"""
    print(f"[{script_name}] {message}", file=sys.stderr)


def wait_for_ui_stable(
    d, timeout=TIMEOUT_SLOW, interval=0.5, script_name="ui_automation"
):
    """
    Wait until the UI hierarchy stops changing.

    Args:
        d: uiautomator2 device instance
        timeout: Maximum time to wait (seconds)
        interval: How often to check UI (seconds)
        script_name: Name of calling script for logging

    Returns:
        True if UI stabilized, False if timeout
    """
    log("Waiting for UI to stabilize...", script_name)
    prev_hierarchy = None
    start = time.time()

    while time.time() - start < timeout:
        current_hierarchy = d.dump_hierarchy(compressed=True)
        if current_hierarchy == prev_hierarchy:
            log("UI stabilized", script_name)
            return True
        prev_hierarchy = current_hierarchy
        time.sleep(interval)

    log("WARNING: UI did not stabilize within timeout", script_name)
    return False


def capture_failure_context(
    d, error_msg, script_name="ui_automation", save_screenshot=True
):
    """
    Capture debugging context on failure.

    Args:
        d: uiautomator2 device instance
        error_msg: Error message describing the failure
        script_name: Name of calling script
        save_screenshot: Whether to save a screenshot to /tmp

    Returns:
        String with failure context
    """
    log(f"[ERROR] {error_msg}", script_name)

    context_parts = [
        "=" * 60,
        f"FAILURE CONTEXT - {script_name}",
        "=" * 60,
        f"Error: {error_msg}",
        f"Timestamp: {datetime.now().isoformat()}",
    ]

    # Get current activity
    try:
        result = subprocess.run(
            ["adb", "shell", "dumpsys", "window", "displays"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.split("\n"):
            if "mCurrentFocus" in line or "mFocusedApp" in line:
                context_parts.append(f"Current focus: {line.strip()}")
                break
    except Exception as e:
        context_parts.append(f"Could not get current activity: {e}")

    # Save screenshot
    if save_screenshot:
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_path = f"/tmp/ui_failure_{script_name}_{timestamp}.png"
            d.screenshot(screenshot_path)
            context_parts.append(f"Screenshot saved: {screenshot_path}")
            log(f"Screenshot saved to {screenshot_path}", script_name)
        except Exception as e:
            context_parts.append(f"Could not save screenshot: {e}")

    # Add concise UI hierarchy (just top-level elements)
    try:
        context_parts.append("\nTop-level UI elements:")
        hierarchy = d.dump_hierarchy()
        lines = hierarchy.split("\n")[:50]
        context_parts.extend(lines)
        if len(hierarchy.split("\n")) > 50:
            line_count = len(hierarchy.split("\n")) - 50
            context_parts.append(f"... ({line_count} more lines)")
    except Exception as e:
        context_parts.append(f"Could not dump UI hierarchy: {e}")

    context_parts.append("=" * 60)

    context = "\n".join(context_parts)
    print(context, file=sys.stderr)
    return context


def fill_login_form(d, username, password, script_name="ui_automation"):
    """
    Fill in the login form with username and password.
    Shared function used by both login_first_time.py and login_additional_user.py.

    Used by verification scripts in the main directory.

    Args:
        d: uiautomator2 device instance
        username: XMPP username
        password: XMPP password
        script_name: Name of calling script for logging

    Returns:
        True if form filled successfully, False otherwise
    """
    log("Filling login form...", script_name)

    # Wait for login form to appear
    jid_field = d(resourceId="eu.siacs.conversations:id/account_jid")
    if not jid_field.wait(timeout=TIMEOUT_SLOW):
        log("[ERROR] Login form did not appear", script_name)
        return False

    log("✓ Login form appeared", script_name)

    # Fill XMPP address
    log(f"Setting XMPP address: {username}", script_name)
    jid_field.set_text(username)
    time.sleep(0.3)

    # Fill password
    log("Setting password...", script_name)
    d(resourceId="eu.siacs.conversations:id/account_password").set_text(password)
    time.sleep(0.3)

    # Hide keyboard
    log("Hiding keyboard...", script_name)
    d.press("back")
    time.sleep(0.3)

    log("✓ Login form filled successfully", script_name)
    return True


def handle_certificate_dialog(d, timeout=TIMEOUT_NORMAL, script_name="ui_automation"):
    """
    Handle XMPP server certificate trust dialog.
    Shared function - was duplicated in both login files.

    Args:
        d: uiautomator2 device instance
        timeout: How long to wait for dialog
        script_name: Name of calling script for logging

    Returns:
        True if dialog was handled, False if no dialog found
    """
    log("Checking for certificate dialog...", script_name)

    always_button = d(text="Always")
    if always_button.wait(timeout=timeout):
        log("✓ Found certificate dialog", script_name)
        log("Clicking 'Always' to trust certificate...", script_name)
        pre_click_hierarchy = d.dump_hierarchy(compressed=True)
        always_button.click()
        # Wait for dialog to disappear
        if not wait_for_screen_change(d, pre_click_hierarchy, timeout=TIMEOUT_FAST):
            log("WARNING: Screen did not change after clicking Always", script_name)
        wait_for_ui_stable(d, timeout=TIMEOUT_NORMAL, script_name=script_name)
        log("✓ Certificate trusted", script_name)
        return True

    log("No certificate dialog found", script_name)
    return False


def handle_publish_avatar_screen(d, script_name="ui_automation"):
    """
    Handle the optional 'Publish avatar' post-login screen.
    Shared function - was duplicated in both login files.

    Args:
        d: uiautomator2 device instance
        script_name: Name of calling script for logging

    Returns:
        True if screen was handled, False if not present
    """
    log("Checking for 'Publish avatar' screen...", script_name)

    if d(text="Publish avatar").wait(timeout=TIMEOUT_FAST):
        log("✓ Found 'Publish avatar' screen", script_name)
        log("Clicking 'Skip' button...", script_name)
        pre_click_hierarchy = d.dump_hierarchy(compressed=True)
        d(resourceId="eu.siacs.conversations:id/cancel_button").click()
        # Wait for screen to change
        if not wait_for_screen_change(d, pre_click_hierarchy, timeout=TIMEOUT_FAST):
            log("WARNING: Screen did not change after clicking Skip", script_name)
        wait_for_ui_stable(d, timeout=TIMEOUT_NORMAL, script_name=script_name)
        log("✓ Skipped avatar setup", script_name)
        return True

    log("No 'Publish avatar' screen found", script_name)
    return False
