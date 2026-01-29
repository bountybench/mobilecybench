"""
Navigation utilities for openHAB UI automation.
"""

# Note: sys.path is configured in __init__.py
from utils.ui_utils import (
    click_then_expect,
    press_back_then_expect,
    wait_and_click,
    wait_for_ui_stable,
)

from .constants import RES_ANDROID_EDIT, TIMEOUT_FAST, TIMEOUT_NORMAL
from .dialogs import click_dialog_ok
from .logger import log
from .screens import (
    is_connected_to_server,
    is_on_initial_screen,
    is_on_local_settings_screen,
)


def navigate_to_settings(d) -> bool:
    """
    Navigate to the Settings screen from the main screen.

    Args:
        d: uiautomator2 device instance

    Returns:
        True if successfully navigated to Settings, False otherwise
    """
    log("Navigating to Settings...")

    # Try opening the drawer menu
    drawer_button = d(description="Open side menu")
    if not drawer_button.exists:
        log("Drawer button not found - trying other navigation methods")
        # Try using the overflow menu
        overflow = d(description="More options")
        if overflow.exists:
            settings_option = d(text="Settings")
            if click_then_expect(d, overflow, settings_option, timeout=TIMEOUT_FAST):
                settings_title = d(text="Settings")
                if click_then_expect(
                    d, settings_option, settings_title, timeout=TIMEOUT_NORMAL
                ):
                    return True
        return False

    # Click drawer to open side menu
    settings_item = d(text="Settings")
    if not click_then_expect(d, drawer_button, settings_item, timeout=TIMEOUT_NORMAL):
        log("WARNING: Side menu did not open")
        return False

    log("✓ Side menu opened")

    # Click Settings in the side menu
    # Wait for the Connection header which is only on the settings screen
    connection_header = d(text="Connection")
    if click_then_expect(d, settings_item, connection_header, timeout=TIMEOUT_NORMAL):
        log("✓ Navigated to Settings screen")
        return True

    return False


def navigate_back_and_save(d) -> bool:
    """
    Navigate back through the settings, saving when prompted.

    Uses press_back_then_expect for robust back navigation and
    wait_and_click for dialog interactions.

    Args:
        d: uiautomator2 device instance

    Returns:
        True if successfully navigated to main screen with connection, False otherwise
    """
    log("Navigating back to main screen...")

    max_back_presses = 5
    for i in range(max_back_presses):
        # Check if we're on the main screen (connected)
        if is_connected_to_server(d):
            log("✓ Already on main screen with connection")
            return True

        # Check for initial screen (connection issue)
        if is_on_initial_screen(d):
            log("Back on initial screen - server connection may have failed")
            return False

        # Define expected states after back press
        def expected_after_back():
            # We expect either: save dialog, connected screen, or initial screen
            return (
                d(text="Save").exists
                or is_connected_to_server(d)
                or is_on_initial_screen(d)
            )

        # Use shared utility for robust back press with expectation
        press_back_then_expect(d, expected_after_back, timeout=TIMEOUT_FAST)

        # Check for save dialog
        save_button = d(text="Save")
        if save_button.exists:
            log("✓ Save dialog appeared - clicking Save")
            try:
                wait_and_click(d, save_button, timeout=TIMEOUT_FAST)
            except SystemExit:
                # wait_and_click may exit on failure, continue navigation
                pass
            wait_for_ui_stable(d)

    return is_connected_to_server(d)


def clear_credentials(d) -> bool:
    """
    Clear username and password if auth is failing.

    Uses shared click_then_expect and wait_and_click utilities for
    robust UI interactions.

    Args:
        d: uiautomator2 device instance

    Returns:
        True if on local settings screen and cleared, False otherwise
    """
    log("Clearing credentials (auth may not be required)...")

    if not is_on_local_settings_screen(d):
        return False

    # Clear username
    username_option = d(text="Username")
    if username_option.exists:
        edit_field = d(resourceId=RES_ANDROID_EDIT)
        if click_then_expect(d, username_option, edit_field, timeout=TIMEOUT_FAST):
            d(resourceId=RES_ANDROID_EDIT).clear_text()
            click_dialog_ok(d)
            wait_for_ui_stable(d)

    # Clear password
    password_option = d(text="Password")
    if password_option.exists:
        password_summary = d(text="Strong password set")
        if password_summary.exists:
            edit_field = d(resourceId=RES_ANDROID_EDIT)
            if click_then_expect(d, password_option, edit_field, timeout=TIMEOUT_FAST):
                d(resourceId=RES_ANDROID_EDIT).clear_text()
                click_dialog_ok(d)
                wait_for_ui_stable(d)

    return True
