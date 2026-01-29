"""
Constants for openHAB UI automation.
"""

# Script identification
SCRIPT_NAME = "openhab_setup_ui"
PACKAGE = "org.openhab.habdroid"

# Timeout constants (in seconds)
TIMEOUT_FAST = 5  # For elements that should appear immediately
TIMEOUT_NORMAL = 10  # For typical screen transitions
TIMEOUT_SLOW = 30  # For network operations

# Default server URL (from emulator's perspective)
DEFAULT_SERVER_URL = "http://10.0.2.2:8080"

# Resource IDs
RES_WIDGET_LABEL = "org.openhab.habdroid:id/widgetlabel"
RES_VOICE_RECOGNITION = "org.openhab.habdroid:id/mainmenu_voice_recognition"
RES_RECYCLERVIEW = "org.openhab.habdroid:id/recyclerview"
RES_SNACKBAR_ACTION = "org.openhab.habdroid:id/snackbar_action"
RES_SKIP_BUTTON = "org.openhab.habdroid:id/skip"
RES_ANDROID_EDIT = "android:id/edit"
RES_ANDROID_BUTTON1 = "android:id/button1"
