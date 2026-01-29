"""
Configuration loading for openHAB UI automation.
"""

import json
import os
from typing import Any

from .constants import DEFAULT_SERVER_URL
from .logger import log

# Path to metadata.json relative to this file (now in apps/openhab/setup_ui/)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
METADATA_PATH = os.path.join(SCRIPT_DIR, "../metadata.json")


def load_server_config() -> dict[str, Any]:
    """
    Load server configuration from metadata.json.

    Returns:
        Dictionary with server_url, username, and password keys.
    """
    try:
        with open(METADATA_PATH, "r") as f:
            metadata = json.load(f)
            return {
                "server_url": metadata.get("emulator_server", DEFAULT_SERVER_URL),
                "username": metadata.get("username"),
                "password": metadata.get("password"),
            }
    except Exception as e:
        log(f"Could not load metadata: {e}")
        return {
            "server_url": DEFAULT_SERVER_URL,
            "username": None,
            "password": None,
        }
