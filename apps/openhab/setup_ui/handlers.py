"""
Screen handlers for openHAB UI automation.

Each handler manages interactions with a specific screen.
"""

from typing import Optional

# Note: sys.path is configured in __init__.py
from utils.ui_utils import (
    click_then_expect,
    wait_and_click,
    wait_for_ui_stable,
)

from .constants import (
    RES_ANDROID_EDIT,
    RES_SKIP_BUTTON,
    RES_SNACKBAR_ACTION,
    TIMEOUT_FAST,
    TIMEOUT_NORMAL,
)
from .dialogs import click_dialog_ok, set_text_in_dialog
from .logger import log


def handle_welcome_screen(d) -> bool:
    """
    Handle the welcome/onboarding screen by clicking SKIP.

    Uses the shared wait_and_click utility for robust clicking
    with built-in retry logic and ANR handling.

    Args:
        d: uiautomator2 device instance

    Returns:
        True if welcome screen was handled, False if not on welcome screen
    """
    log("Checking for welcome screen...")

    skip_button = d(text="SKIP")
    if not skip_button.exists:
        skip_button = d(resourceId=RES_SKIP_BUTTON)

    if not skip_button.exists:
        log("Not on welcome screen")
        return False

    log("✓ Found welcome screen - clicking SKIP")

    try:
        wait_and_click(d, skip_button, timeout=TIMEOUT_FAST)
        log("✓ Skipped welcome screen")
        return True
    except SystemExit:
        log("WARNING: Failed to click SKIP button")
        return False


def handle_initial_screen(d) -> bool:
    """
    Handle the initial 'server not found' screen.

    Args:
        d: uiautomator2 device instance

    Returns:
        True if successfully navigated to Settings, False otherwise
    """
    log("Checking for initial setup screen...")

    go_to_settings = d(text="Go to settings")
    if not go_to_settings.exists:
        log("Not on initial screen")
        return False

    log("✓ Found initial setup screen - clicking 'Go to settings'")

    settings_title = d(text="Settings")
    if click_then_expect(d, go_to_settings, settings_title, timeout=TIMEOUT_NORMAL):
        log("✓ Navigated to Settings screen")
        return True

    log("WARNING: Failed to navigate to Settings")
    return False


def handle_settings_screen(d) -> bool:
    """
    Handle the Settings screen - navigate to Add server or existing server.

    Args:
        d: uiautomator2 device instance

    Returns:
        True if successfully navigated to Edit server, False otherwise
    """
    log("On Settings screen - looking for server configuration...")

    existing_server = d(textStartsWith="Server ")
    add_server = d(text="Add server")

    if existing_server.exists:
        log("✓ Found existing server - clicking to edit")
        edit_server_title = d(text="Edit server")
        if click_then_expect(
            d, existing_server, edit_server_title, timeout=TIMEOUT_NORMAL
        ):
            log("✓ Navigated to Edit server screen")
            return True
    elif add_server.exists:
        log("✓ Found 'Add server' - clicking to add new server")
        edit_server_title = d(text="Edit server")
        if click_then_expect(d, add_server, edit_server_title, timeout=TIMEOUT_NORMAL):
            log("✓ Navigated to Edit server screen")
            return True

    log("WARNING: Could not find server configuration option")
    return False


def handle_edit_server_screen(d) -> bool:
    """
    Handle the Edit server screen - navigate to Local settings.

    Args:
        d: uiautomator2 device instance

    Returns:
        True if successfully navigated to Local settings, False otherwise
    """
    log("On Edit server screen - clicking 'Local'...")

    local_option = d(text="Local")
    if not local_option.exists:
        log("WARNING: 'Local' option not found")
        return False

    local_url_option = d(text="Local server URL")

    if click_then_expect(d, local_option, local_url_option, timeout=TIMEOUT_NORMAL):
        log("✓ Navigated to Local settings screen")
        return True

    return False


def handle_local_settings(
    d, server_url: str, username: Optional[str] = None, password: Optional[str] = None
) -> bool:
    """
    Configure local server settings.

    Args:
        d: uiautomator2 device instance
        server_url: URL of the openHAB server
        username: Optional username for authentication
        password: Optional password for authentication

    Returns:
        True if settings were configured successfully, False otherwise
    """
    log(f"Configuring local server: {server_url}")

    # Click on Local server URL
    url_option = d(text="Local server URL")
    if not url_option.exists:
        log("WARNING: 'Local server URL' option not found")
        return False

    edit_field = d(resourceId=RES_ANDROID_EDIT)
    if not click_then_expect(d, url_option, edit_field, timeout=TIMEOUT_NORMAL):
        log("WARNING: URL dialog did not open")
        return False

    log("✓ URL dialog opened")

    if not set_text_in_dialog(d, server_url):
        return False

    if not click_dialog_ok(d):
        return False

    wait_for_ui_stable(d)

    # Verify URL was set
    url_summary = d(textContains=server_url)
    if url_summary.exists:
        log("✓ Server URL configured successfully")

    # Handle username if provided
    if username:
        log(f"Setting username: {username}")
        username_option = d(text="Username")
        edit_field = d(resourceId=RES_ANDROID_EDIT)

        if click_then_expect(d, username_option, edit_field, timeout=TIMEOUT_NORMAL):
            set_text_in_dialog(d, username)
            click_dialog_ok(d)
            wait_for_ui_stable(d)

    # Handle password if provided
    if password:
        log("Setting password...")
        password_option = d(text="Password")
        edit_field = d(resourceId=RES_ANDROID_EDIT)

        if click_then_expect(d, password_option, edit_field, timeout=TIMEOUT_NORMAL):
            set_text_in_dialog(d, password)
            click_dialog_ok(d)
            wait_for_ui_stable(d)

    return True


def handle_permissions_snackbar(d) -> None:
    """
    Handle the permissions snackbar that may appear.

    Uses the shared wait_and_click utility for robust clicking.

    Args:
        d: uiautomator2 device instance
    """
    allow_button = d(resourceId=RES_SNACKBAR_ACTION)
    if allow_button.exists:
        log("Found permissions snackbar - clicking Allow")
        try:
            wait_and_click(d, allow_button, timeout=TIMEOUT_FAST)
        except SystemExit:
            log("WARNING: Failed to click snackbar action")
        handle_system_permissions(d)


def handle_system_permissions(d, max_permissions: int = 5) -> int:
    """
    Handle Android system permission dialogs.

    Uses the shared wait_and_click utility for robust clicking
    with built-in retry logic.

    Args:
        d: uiautomator2 device instance
        max_permissions: Maximum number of permission dialogs to handle

    Returns:
        Number of permission dialogs handled
    """
    permissions_handled = 0

    for _ in range(max_permissions):
        allow_button = d(text="Allow")
        allow_button_upper = d(text="ALLOW")

        if allow_button.exists:
            log("Found permission dialog - clicking Allow")
            try:
                wait_and_click(d, allow_button, timeout=TIMEOUT_FAST)
                permissions_handled += 1
            except SystemExit:
                break
        elif allow_button_upper.exists:
            log("Found permission dialog - clicking ALLOW")
            try:
                wait_and_click(d, allow_button_upper, timeout=TIMEOUT_FAST)
                permissions_handled += 1
            except SystemExit:
                break
        else:
            break

    if permissions_handled > 0:
        log(f"✓ Handled {permissions_handled} permission dialog(s)")

    return permissions_handled
