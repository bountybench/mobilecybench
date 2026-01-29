"""
Screen detection functions for openHAB UI automation.

These functions detect which screen the app is currently on.
"""

from .constants import RES_RECYCLERVIEW, RES_VOICE_RECOGNITION, RES_WIDGET_LABEL
from .logger import log


def is_connected_to_server(d) -> bool:
    """
    Check if the app is connected to an openHAB server.

    Connected indicators:
    - Widget labels visible (e.g., "Test Switch", "Smart Home Controls")
    - Main menu voice recognition button visible
    - Sitemap recyclerview visible

    Args:
        d: uiautomator2 device instance

    Returns:
        True if connected to server, False otherwise
    """
    if d(resourceId=RES_WIDGET_LABEL).exists:
        log("✓ Found widget labels - app is connected to server")
        return True

    if d(resourceId=RES_VOICE_RECOGNITION).exists:
        log("✓ Found voice recognition button - app is connected to server")
        return True

    if d(
        className="androidx.recyclerview.widget.RecyclerView",
        resourceId=RES_RECYCLERVIEW,
    ).exists:
        log("✓ Found sitemap recyclerview - app is connected to server")
        return True

    # Check for connected-but-empty state (e.g. "No sitemaps available")
    if d(textContains="No sitemaps").exists:
        log("✓ Connected to server (no sitemaps available)")
        return True

    # Check for the main toolbar with the hamburger menu (indicates active connection)
    if d(description="Open side menu").exists:
        log("✓ Found main navigation drawer - app is connected to server")
        return True

    return False


def is_on_welcome_screen(d) -> bool:
    """Check if on the welcome/onboarding screen."""
    if d(text="Welcome to openHAB").exists:
        return True
    if d(resourceId="org.openhab.habdroid:id/skip").exists:
        return True
    return False


def is_on_initial_screen(d) -> bool:
    """Check if on the initial 'server not found' screen."""
    if d(text="Go to settings").exists:
        return True
    if d(text="Turn on demo mode").exists:
        return True
    if d(textContains="didn't find an openHAB server").exists:
        return True
    return False


def is_on_settings_screen(d) -> bool:
    """Check if on the main Settings screen."""
    toolbar_title = d(className="android.widget.TextView", text="Settings")
    connection_header = d(text="Connection")
    return toolbar_title.exists and connection_header.exists


def is_on_edit_server_screen(d) -> bool:
    """Check if on the Edit Server screen."""
    toolbar_title = d(className="android.widget.TextView", text="Edit server")
    return toolbar_title.exists


def is_on_local_settings_screen(d) -> bool:
    """Check if on the Local settings screen."""
    toolbar_title = d(className="android.widget.TextView", text="Local")
    return toolbar_title.exists


def is_on_auth_failure_screen(d) -> bool:
    """Check if showing authentication failure."""
    return d(textContains="Authentication failed").exists
