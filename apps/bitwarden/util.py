"""
This module contains general-purpose utility functions for the Bitwarden tests,
including ADB commands and server management.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

BITWARDEN_PKG = "com.x8bit.bitwarden.dev"
SERVER_URL = "http://10.0.2.2:8000"

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
        print(
            f"[ERROR] Failed to run adb command: {' '.join(full_cmd)}. Is ADB installed and in your PATH? Error: {e}",
            file=sys.stderr,
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
        print("❌ secrets.json not found.", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError:
        print("❌ Invalid JSON in secrets.json", file=sys.stderr)
        sys.exit(1)


# =============================================================================
# SERVER MANAGEMENT
# =============================================================================


def ensure_server_running():
    """
    Ensures the Vaultwarden server is running before testing.
    Returns boolean of whether the server is available.
    """
    print("Ensuring Vaultwarden server is running...", file=sys.stderr)

    # Check if server is already running
    try:
        with urllib.request.urlopen(
            "http://localhost:8000/alive", timeout=5
        ) as response:
            if response.status == 200:
                print("[PASS] Vaultwarden server is already running.", file=sys.stderr)
                return True
    except:
        pass

    # Server not running, try to start it
    print("Vaultwarden server not running. Attempting to start it...", file=sys.stderr)
    try:
        # Start the vaultwarden service
        subprocess.run(
            ["docker", "compose", "up", "-d", "vaultwarden"],
            capture_output=True,
            check=True,
            timeout=30,
        )

        # Wait for server to be ready
        print("Waiting for Vaultwarden server to be ready...", file=sys.stderr)
        for i in range(30):  # Wait up to 30 seconds
            try:
                with urllib.request.urlopen(
                    "http://localhost:8000/alive", timeout=5
                ) as response:
                    if response.status == 200:
                        print(
                            "[PASS] Vaultwarden server started successfully.",
                            file=sys.stderr,
                        )
                        return True
            except:
                time.sleep(1)

        print(
            "[FAIL] Vaultwarden server failed to start within timeout.", file=sys.stderr
        )
        return False

    except subprocess.TimeoutExpired:
        print("[FAIL] Timeout starting Vaultwarden server.", file=sys.stderr)
        return False
    except subprocess.CalledProcessError as e:
        print(f"[FAIL] Failed to start Vaultwarden server: {e}", file=sys.stderr)
        return False
