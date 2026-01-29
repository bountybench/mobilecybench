#!/usr/bin/env python3
"""
UI automation script for setting up the openHAB Android app.

This script:
1. Launches the openHAB app
2. Configures the local server URL (http://10.0.2.2:8080)
3. Handles different starting states (fresh install, already configured, mid-flow)
4. Verifies successful connection to the openHAB server

Complete flow (verified manually):
1. Initial screen: "We didn't find an openHAB server" → Click "Go to settings"
2. Settings screen → Click "Add server" (or "Server openHAB" if exists)
3. Edit server screen → Click "Local"
4. Local settings → Set "Local server URL" to http://10.0.2.2:8080
5. Navigate back, saving changes when prompted
6. Verify sitemap is visible on main screen
"""
import argparse
import os
import sys

# Add the project root to the path for imports
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "../../"))
sys.path.insert(0, PROJECT_ROOT)

# Import from the modular setup_ui package
from setup_ui import (  # noqa: E402
    PACKAGE,
    TIMEOUT_NORMAL,
    TIMEOUT_SLOW,
    clear_credentials,
    handle_edit_server_screen,
    handle_initial_screen,
    handle_local_settings,
    handle_permissions_snackbar,
    handle_settings_screen,
    # Handlers
    handle_welcome_screen,
    # Screen detection
    is_connected_to_server,
    is_on_auth_failure_screen,
    is_on_edit_server_screen,
    is_on_initial_screen,
    is_on_local_settings_screen,
    is_on_settings_screen,
    is_on_welcome_screen,
    load_server_config,
    log,
    navigate_back_and_save,
    # Navigation
    navigate_to_settings,
)

from utils.ui_utils import initialize_ui_automation, wait_for_ui_stable  # noqa: E402


def main():
    log("=" * 60)
    log("openHAB Android App Setup Automation")
    log("=" * 60)

    # Parse arguments
    parser = argparse.ArgumentParser(description="openHAB app setup automation")
    parser.add_argument("--server-url", default=None, help="Server URL to configure")
    parser.add_argument("--username", default=None, help="Username (optional)")
    parser.add_argument("--password", default=None, help="Password (optional)")
    parser.add_argument(
        "--no-auth", action="store_true", help="Skip authentication setup"
    )
    args = parser.parse_args()

    # Load configuration
    config = load_server_config()
    server_url = args.server_url or config["server_url"]
    username = None if args.no_auth else (args.username or config["username"])
    password = None if args.no_auth else (args.password or config["password"])

    log(f"Server URL: {server_url}")
    if username:
        log(f"Username: {username}")
    if password:
        log(f"Password: {'*' * len(password)}")

    try:
        # Connect to device
        log("\nConnecting to device...")
        d = initialize_ui_automation()

        # Launch the app
        log("\nLaunching openHAB app...")
        d.app_start(PACKAGE, stop=True, wait=True)
        wait_for_ui_stable(d, timeout=TIMEOUT_SLOW)

        # Check if already connected
        if is_connected_to_server(d):
            log("\n" + "=" * 60)
            log("SUCCESS: App is already connected to server")
            log("=" * 60)

            # Handle any permission snackbars
            handle_permissions_snackbar(d)
            sys.exit(0)

        # Determine current state and navigate accordingly
        log("\nAnalyzing current app state...")

        # State 0: Welcome/onboarding screen (first time launch)
        if is_on_welcome_screen(d):
            log("State: Welcome screen")
            handle_welcome_screen(d)
            wait_for_ui_stable(d)

        # State 1: Initial screen (server not found)
        if is_on_initial_screen(d):
            log("State: Initial setup screen")
            if not handle_initial_screen(d):
                log("[ERROR] Failed to navigate from initial screen")
                sys.exit(1)

        # State 2: Settings screen
        elif is_on_settings_screen(d):
            log("State: Settings screen")
            # Already on settings, proceed

        # State 3: Edit server screen
        elif is_on_edit_server_screen(d):
            log("State: Edit server screen")
            # Skip to edit server handling

        # State 4: Local settings screen
        elif is_on_local_settings_screen(d):
            log("State: Local settings screen")
            # Skip to local settings handling

        # State 5: Auth failure screen
        elif is_on_auth_failure_screen(d):
            log("State: Authentication failure - navigating to settings")
            if not navigate_to_settings(d):
                log("[ERROR] Failed to navigate to settings from main screen")
                sys.exit(1)

        else:
            # Unknown state - try to navigate to settings
            log("State: Unknown - attempting to navigate to settings")
            if not navigate_to_settings(d):
                log("[ERROR] Failed to navigate to settings")
                sys.exit(1)

        # Now we should be on or past the Settings screen
        wait_for_ui_stable(d)

        # Handle Settings screen if we're there
        if is_on_settings_screen(d):
            if not handle_settings_screen(d):
                log("[ERROR] Failed to navigate to server configuration")
                sys.exit(1)

        # Handle Edit server screen if we're there
        if is_on_edit_server_screen(d):
            if not handle_edit_server_screen(d):
                log("[ERROR] Failed to navigate to Local settings")
                sys.exit(1)

        # Handle Local settings screen
        if is_on_local_settings_screen(d):
            if not handle_local_settings(d, server_url, username, password):
                log("[ERROR] Failed to configure local server settings")
                sys.exit(1)

        # Navigate back and save
        if not navigate_back_and_save(d):
            # Check if auth failed
            if is_on_auth_failure_screen(d) or is_on_initial_screen(d):
                log("Server connection failed - trying without credentials...")

                # Navigate back to settings and clear credentials
                if navigate_to_settings(d):
                    if handle_settings_screen(d):
                        if handle_edit_server_screen(d):
                            clear_credentials(d)
                            navigate_back_and_save(d)

        # Final check - retry for up to 60s since the app connects asynchronously
        import time

        max_wait = 60
        poll_interval = 5
        start_time = time.time()
        connected = False

        log("Waiting for app to connect to server (up to 60s)...")
        while time.time() - start_time < max_wait:
            wait_for_ui_stable(d, timeout=TIMEOUT_NORMAL)

            # Handle any permission snackbars
            handle_permissions_snackbar(d)

            if is_connected_to_server(d):
                connected = True
                break

            elapsed = int(time.time() - start_time)
            log(f"Not connected yet ({elapsed}s elapsed), retrying...")
            time.sleep(poll_interval)

        if connected:
            log("\n" + "=" * 60)
            log("SUCCESS: openHAB app configured and connected to server")
            log("=" * 60)
            sys.exit(0)
        else:
            log("\n" + "=" * 60)
            log("[ERROR] Failed to connect to openHAB server")
            log("=" * 60)
            sys.exit(1)

    except KeyboardInterrupt:
        log("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        log(f"[ERROR] Unexpected error: {e}")
        import traceback

        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
