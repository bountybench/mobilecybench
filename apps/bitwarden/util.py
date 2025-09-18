"""
This module contains general-purpose utility functions for the Bitwarden tests,
including ADB commands and server management.
"""

import json
import logging
import os
import subprocess
import sys
import time
import urllib.request

BITWARDEN_PKG = "com.x8bit.bitwarden.dev"
SERVER_URL = "http://10.0.2.2:8000"

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
        return subprocess.check_output(full_cmd, stderr=subprocess.DEVNULL, text=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.error(
            "Failed to run adb command: %s. Is ADB installed and in your PATH? Error: %s",
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
        script_dir = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(script_dir, "secrets.json")) as f:
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
    Ensures the Vaultwarden server is running before testing.
    Returns boolean of whether the server is available.
    """
    logger.info("Ensuring Vaultwarden server is running...")

    # Check if server is already running
    try:
        with urllib.request.urlopen(
            "http://localhost:8000/alive", timeout=5
        ) as response:
            if response.status == 200:
                logger.info("Vaultwarden server is already running.")
                return True
    except Exception:
        pass

    # Server not running, try to start it
    logger.info("Vaultwarden server not running. Attempting to start it...")
    try:
        # Get the bitwarden directory to run docker compose from
        bitwarden_dir = os.path.dirname(os.path.abspath(__file__))

        # Start the vaultwarden service
        subprocess.run(
            ["docker", "compose", "up", "-d", "vaultwarden"],
            capture_output=True,
            check=True,
            timeout=30,
            cwd=bitwarden_dir,
        )

        # Wait for server to be ready
        logger.info("Waiting for Vaultwarden server to be ready...")
        for i in range(30):  # Wait up to 30 seconds
            try:
                with urllib.request.urlopen(
                    "http://localhost:8000/alive", timeout=5
                ) as response:
                    if response.status == 200:
                        logger.info("Vaultwarden server started successfully.")
                        return True
            except Exception:
                time.sleep(1)

        logger.error("Vaultwarden server failed to start within timeout.")
        return False

    except subprocess.TimeoutExpired:
        logger.error("Timeout starting Vaultwarden server.")
        return False
    except subprocess.CalledProcessError as e:
        logger.error("Failed to start Vaultwarden server: %s", e)
        return False
