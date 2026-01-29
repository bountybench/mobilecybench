"""
Dialog handling utilities for openHAB UI automation.
"""

import time

# Note: sys.path is configured in __init__.py
from utils.ui_utils import wait_and_click, wait_and_set_text

from .constants import RES_ANDROID_BUTTON1, RES_ANDROID_EDIT
from .logger import log


def set_text_in_dialog(
    d, text: str, clear_first: bool = True, max_retries: int = 3
) -> bool:
    """
    Set text in a dialog input field.

    Uses the shared wait_and_set_text utility for robust text entry
    with built-in retry logic and ANR handling.

    Args:
        d: uiautomator2 device instance
        text: Text to enter
        clear_first: Whether to clear existing text first
        max_retries: Number of retry attempts if setting text fails

    Returns:
        True if successful, False otherwise
    """
    # Wait a moment for dialog animation to complete
    time.sleep(0.5)

    edit_field = d(resourceId=RES_ANDROID_EDIT)
    if not edit_field.exists:
        log("WARNING: Edit field not found in dialog")
        return False

    try:
        if clear_first:
            edit_field.clear_text()
        # Use shared utility for robust text setting with retries
        wait_and_set_text(d, edit_field, text, max_retries=max_retries)
        log(f"✓ Set text to: {text}")
        return True
    except SystemExit:
        # wait_and_set_text calls _fatal on failure which exits
        log(f"WARNING: Failed to set text after {max_retries} attempts")
        return False
    except Exception as e:
        log(f"WARNING: Failed to set text: {e}")
        return False


def click_dialog_ok(d) -> bool:
    """
    Click the OK button in a dialog.

    Uses the shared wait_and_click utility for robust clicking
    with built-in retry logic and ANR handling.

    Args:
        d: uiautomator2 device instance

    Returns:
        True if successful, False otherwise
    """
    ok_button = d(resourceId=RES_ANDROID_BUTTON1)
    if not ok_button.exists:
        ok_button = d(text="OK")

    if not ok_button.exists:
        log("WARNING: OK button not found")
        return False

    try:
        # Use shared utility for robust clicking with retries
        wait_and_click(d, ok_button, timeout=5)
        log("✓ Clicked OK")
        return True
    except SystemExit:
        # wait_and_click calls _fatal on failure which exits
        log("WARNING: Failed to click OK button")
        return False
