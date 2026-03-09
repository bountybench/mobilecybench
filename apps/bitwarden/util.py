"""
This module contains general-purpose utility functions for the Bitwarden tests,
including ADB commands and server management.
"""

import json
import logging
import os
import subprocess
import sys
import urllib.request

# Resolve metadata relative to the app directory
app_dir = os.path.dirname(os.path.abspath(__file__))
metadata_path = os.path.join(app_dir, "metadata.json")
try:
    with open(metadata_path, "r") as f:
        metadata = json.load(f)
except Exception:
    metadata = {}

BITWARDEN_PKG = metadata.get("package_name", "com.x8bit.bitwarden.dev")
# Use emulator_server from metadata, fallback to standard emulator-to-host URL
SERVER_URL = metadata.get("emulator_server", "http://10.0.2.2:8000")

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
logger = logging.getLogger("mobilecybench.bitwarden.util")
logger.setLevel("INFO")
_handler = logging.StreamHandler(stream=sys.stderr)
_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logger.handlers[:] = [_handler]
logger.propagate = False

# =============================================================================
# ADB UTILITY FUNCTION
# =============================================================================


def adb(cmd):
    """
    Runs ADB commands with error handling.

    Args:
        cmd: List of command arguments (excluding 'adb')

    Returns:
        Command output as string, or None if failed
    """
    full_cmd = ["adb"] + cmd
    try:
        # Use check_output for capturing output, but check for adb availability
        return subprocess.check_output(full_cmd, stderr=subprocess.DEVNULL, text=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.error(
            "Failed to run adb command: %s. Error: %s",
            " ".join(full_cmd),
            e,
        )
        return None


# =============================================================================
# LOAD SECRETS
# =============================================================================


def load_secrets():
    """Loads secrets from secrets.json, exiting if the file is missing or invalid."""
    try:
        # Resolve secrets.json relative to the app directory
        app_dir = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(app_dir, "secrets.json")) as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("secrets.json not found.")
        sys.exit(1)
    except json.JSONDecodeError:
        logger.error("Invalid JSON in secrets.json")
        sys.exit(1)


# =============================================================================
# SERVER MANAGEMENT
# =============================================================================


def ensure_server_running():
    """
    Ensures the Vaultwarden server is responsive.
    Note: orchestration is handled by start_runtime.sh.
    """
    logger.info("Checking if Vaultwarden server is responsive...")

    try:
        # We check localhost:8000 because this runs on the host (CI runner)
        with urllib.request.urlopen(
            "http://localhost:8000/alive", timeout=10
        ) as response:
            if response.status == 200:
                logger.info("Vaultwarden server is responsive.")
                return True
    except Exception as e:
        logger.error("Vaultwarden server is NOT responsive: %s", e)
        return False

    return False
