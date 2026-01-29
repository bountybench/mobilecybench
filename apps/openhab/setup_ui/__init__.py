"""
UI automation package for setting up the openHAB Android app.

This package provides modular components for:
- Screen detection and state management
- Navigation helpers
- Dialog handling
- Server configuration
"""

import os
import sys

# Add project root to path for utils imports (must be before other imports)
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, "../../"))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from .config import load_server_config  # noqa: E402
from .constants import (  # noqa: E402
    PACKAGE,
    SCRIPT_NAME,
    TIMEOUT_FAST,
    TIMEOUT_NORMAL,
    TIMEOUT_SLOW,
)
from .dialogs import click_dialog_ok, set_text_in_dialog  # noqa: E402
from .handlers import (  # noqa: E402
    handle_edit_server_screen,
    handle_initial_screen,
    handle_local_settings,
    handle_permissions_snackbar,
    handle_settings_screen,
    handle_system_permissions,
    handle_welcome_screen,
)
from .logger import log  # noqa: E402
from .navigation import (  # noqa: E402
    clear_credentials,
    navigate_back_and_save,
    navigate_to_settings,
)
from .screens import (  # noqa: E402
    is_connected_to_server,
    is_on_auth_failure_screen,
    is_on_edit_server_screen,
    is_on_initial_screen,
    is_on_local_settings_screen,
    is_on_settings_screen,
    is_on_welcome_screen,
)

__all__ = [
    # Constants
    "PACKAGE",
    "SCRIPT_NAME",
    "TIMEOUT_FAST",
    "TIMEOUT_NORMAL",
    "TIMEOUT_SLOW",
    # Config
    "load_server_config",
    # Screen detection
    "is_connected_to_server",
    "is_on_welcome_screen",
    "is_on_initial_screen",
    "is_on_settings_screen",
    "is_on_edit_server_screen",
    "is_on_local_settings_screen",
    "is_on_auth_failure_screen",
    # Handlers
    "handle_welcome_screen",
    "handle_initial_screen",
    "handle_settings_screen",
    "handle_edit_server_screen",
    "handle_local_settings",
    "handle_permissions_snackbar",
    "handle_system_permissions",
    # Navigation
    "navigate_to_settings",
    "navigate_back_and_save",
    "clear_credentials",
    # Dialogs
    "set_text_in_dialog",
    "click_dialog_ok",
    # Logging
    "log",
]
