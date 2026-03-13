#!/usr/bin/env python3
"""
Shared utilities for Gotify UI automation scripts.

This module re-exports shared utilities from utils.ui_utils and provides
app-specific helpers for the Gotify push notification client.
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
