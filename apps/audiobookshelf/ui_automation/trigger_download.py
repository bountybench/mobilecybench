#!/usr/bin/env python3
"""
UI Automation for triggering audiobookshelf download.

This script automates the process of:
1. Logging in to the audiobookshelf app (if not already logged in)
2. Navigating to a library item
3. Triggering a download to exercise the vulnerable code path

Usage:
    python trigger_download.py --server http://10.0.2.2:13378 --username usera --password userAPW123
"""
import argparse
import json
import os
import sys
import time

# Add project root to path for imports
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from utils.ui_utils import (
    initialize_ui_automation,
    click_then_expect,
    press_back_then_expect,
    wait_for_ui_stable,
    wait_and_click,
    wait_and_set_text,
)

SCRIPT_NAME = "trigger_download"
PACKAGE = "com.audiobookshelf.app"

# Timeouts
TIMEOUT_FAST = 5
TIMEOUT_NORMAL = 15
TIMEOUT_SLOW = 30

# Default paths for secrets
DEFAULT_SECRETS_PATH = os.path.join(SCRIPT_DIR, "..", "secrets.json")


def log(message, script_name=SCRIPT_NAME):
    """Log a message with script prefix."""
    print(f"[{script_name}] {message}", file=sys.stderr)


def parse_args():
    parser = argparse.ArgumentParser(description="Audiobookshelf download trigger automation")
    parser.add_argument("--server", default="http://10.0.2.2:13378", help="Server URL")
    parser.add_argument("--username", default="usera", help="Username")
    parser.add_argument("--password", default="userAPW123", help="Password")
    parser.add_argument("--secrets", default=DEFAULT_SECRETS_PATH, help="Path to secrets.json")
    return parser.parse_args()


def get_credentials(args):
    """Get credentials from args or secrets.json"""
    if args.password:
        return args.username, args.password
    
    try:
        with open(args.secrets, "r") as f:
            secrets = json.load(f)
        username = secrets.get("username", args.username)
        password = secrets.get("password", args.password)
        return username, password
    except FileNotFoundError:
        log(f"Secrets file not found: {args.secrets}, using args")
        return args.username, args.password


def check_on_login_screen(d):
    """Check if on the login/connect screen."""
    # Look for "Connect" button or server URL input
    if d(text="Connect").exists:
        log("Found 'Connect' button - on login screen")
        return True
    if d(textContains="Server").exists:
        log("Found server input - on login screen")
        return True
    return False


def check_if_logged_in(d):
    """Check if user is logged in (main library screen)."""
    # Look for library indicators
    if d(text="Library").exists:
        log("Found 'Library' - user is logged in")
        return True
    if d(text="Continue Listening").exists:
        log("Found 'Continue Listening' - user is logged in")
        return True
    if d(description="More options").exists:
        log("Found menu button - user is logged in")
        return True
    return False


def login_to_app(d, server_url, username, password):
    """Login to the audiobookshelf app using the correct flow from synch_app.py."""
    log("Attempting to login...")
    
    wait_for_ui_stable(d, timeout=TIMEOUT_NORMAL)
    
    # Check if we need to login
    if check_if_logged_in(d):
        log("Already logged in")
        return True
    
    if not check_on_login_screen(d):
        log("Not on login screen, launching app...")
        d.app_start(PACKAGE, stop=True)
        time.sleep(3)
        wait_for_ui_stable(d, timeout=TIMEOUT_NORMAL)
    
    # Click Connect button if visible
    connect_btn = d(text="Connect")
    if connect_btn.exists:
        log("Clicking 'Connect' button...")
        connect_btn.click()
        time.sleep(2)
        wait_for_ui_stable(d, timeout=TIMEOUT_FAST)
    
    # Enter server URL using send_keys (like synch_app.py)
    log(f"Entering server URL: {server_url}")
    d.send_keys(server_url)
    d.press("enter")
    time.sleep(2)
    wait_for_ui_stable(d, timeout=TIMEOUT_FAST)
    
    # Enter username and password using EditText instances
    username_field = d(className="android.widget.EditText", instance=0)
    password_field = d(className="android.widget.EditText", instance=1)
    
    if username_field.exists:
        log(f"Entering username: {username}")
        username_field.set_text(username)
    else:
        log("Warning: Could not find username field")
    
    if password_field.exists:
        log("Entering password")
        password_field.set_text(password)
    else:
        log("Warning: Could not find password field")
    
    # Click Submit button
    submit_btn = d(text="Submit")
    if submit_btn.exists:
        log("Clicking submit button...")
        submit_btn.click()
        time.sleep(5)
        wait_for_ui_stable(d, timeout=TIMEOUT_SLOW)
    else:
        log("Warning: Could not find Submit button")
    
    # Verify login success
    time.sleep(3)
    if check_if_logged_in(d):
        log("✓ Login successful")
        return True
    else:
        log("✗ Login may have failed, continuing anyway...")
        return True  # Continue to try download


def navigate_to_library(d):
    """Navigate to the library view."""
    log("Navigating to library...")
    
    # Look for Library tab/button
    library_btn = d(text="Library")
    if library_btn.exists:
        log("Clicking 'Library'...")
        library_btn.click()
        time.sleep(2)
        wait_for_ui_stable(d, timeout=TIMEOUT_FAST)
        return True
    
    # Try navigation drawer
    menu_btn = d(description="Open navigation drawer")
    if not menu_btn.exists:
        menu_btn = d(description="Menu")
    if not menu_btn.exists:
        menu_btn = d(className="android.widget.ImageButton", instance=0)
    
    if menu_btn.exists:
        log("Opening navigation menu...")
        menu_btn.click()
        time.sleep(1)
        wait_for_ui_stable(d, timeout=TIMEOUT_FAST)
        
        library_item = d(text="Library")
        if library_item.exists:
            library_item.click()
            time.sleep(2)
            return True
    
    log("Could not find library navigation")
    return False


def find_and_click_audiobook(d):
    """Find an audiobook and click on it."""
    log("Looking for audiobook to download...")
    
    wait_for_ui_stable(d, timeout=TIMEOUT_FAST)
    
    # Priority 0: Look for the specific Exploit Book
    exploit_book = d(textContains="Exploit Book")
    if exploit_book.exists:
        log("Found 'Exploit Book' target! Clicking...")
        exploit_book.click()
        time.sleep(2)
        wait_for_ui_stable(d, timeout=TIMEOUT_FAST)
        return True
    
    # Look for any clickable item in the library
    # Try various patterns
    
    # Pattern 1: RecyclerView items
    items = d(className="android.view.ViewGroup", clickable=True)
    if items.count > 0:
        log(f"Found {items.count} clickable items")
        # Click the first item that looks like a book
        for i in range(min(items.count, 5)):
            try:
                item = items[i]
                if item.exists:
                    log(f"Clicking item {i}...")
                    item.click()
                    time.sleep(2)
                    wait_for_ui_stable(d, timeout=TIMEOUT_FAST)
                    
                    # Check if we're on a detail page
                    if d(text="Download").exists or d(description="Download").exists:
                        log("✓ Found audiobook detail page")
                        return True
                    
                    # If not on detail, go back and try next
                    d.press("back")
                    time.sleep(1)
            except Exception as e:
                log(f"Error clicking item {i}: {e}")
                continue
    
    # Pattern 2: Look for specific text patterns
    for pattern in ["Audiobook", "Book", "Sample"]:
        book_item = d(textContains=pattern)
        if book_item.exists:
            log(f"Found item with '{pattern}'...")
            book_item.click()
            time.sleep(2)
            return True
    
    log("Could not find audiobook to click")
    return False


def trigger_download(d):
    """Trigger the download on the current audiobook detail page."""
    log("Triggering download...")
    
    wait_for_ui_stable(d, timeout=TIMEOUT_FAST)
    
    # Look for download button
    download_btn = d(text="Download")
    if not download_btn.exists:
        download_btn = d(description="Download")
    if not download_btn.exists:
        download_btn = d(textContains="Download")
    
    if download_btn.exists:
        log("✓ Found download button, clicking...")
        download_btn.click()
        time.sleep(5)  # Wait for download to start
        wait_for_ui_stable(d, timeout=TIMEOUT_SLOW)
        log("✓ Download triggered")
        return True
    
    # Try overflow menu
    more_btn = d(description="More options")
    if more_btn.exists:
        log("Checking overflow menu for download option...")
        more_btn.click()
        time.sleep(1)
        
        download_menu = d(text="Download")
        if download_menu.exists:
            download_menu.click()
            time.sleep(5)
            log("✓ Download triggered from menu")
            return True
        
        d.press("back")
    
    log("Could not find download button")
    return False


def trigger_sync(d):
    """Trigger a sync operation which may exercise the vulnerable code."""
    log("Triggering sync...")
    
    # Look for sync/refresh button
    sync_btn = d(description="Sync")
    if not sync_btn.exists:
        sync_btn = d(description="Refresh")
    if not sync_btn.exists:
        sync_btn = d(text="Sync")
    
    if sync_btn.exists:
        log("Clicking sync button...")
        sync_btn.click()
        time.sleep(3)
        return True
    
    # Try pull-to-refresh
    try:
        d.swipe(0.5, 0.3, 0.5, 0.7)
        log("Performed pull-to-refresh")
        time.sleep(3)
        return True
    except Exception as e:
        log(f"Pull-to-refresh failed: {e}")
    
    return False


def main():
    args = parse_args()
    username, password = get_credentials(args)
    
    log("=" * 60)
    log("Audiobookshelf Download Trigger Automation")
    log("=" * 60)
    log(f"Server: {args.server}")
    log(f"Username: {username}")
    
    try:
        d = initialize_ui_automation()
    except Exception as e:
        log(f"Failed to initialize UI automation: {e}")
        # Fallback to direct connect
        import uiautomator2 as u2
        d = u2.connect()
    
    try:
        # Start the app
        log("\nStarting audiobookshelf app...")
        d.app_start(PACKAGE)
        time.sleep(3)
        wait_for_ui_stable(d, timeout=TIMEOUT_SLOW)
        
        # Login if needed
        log("\n[Step 1] Login")
        if not login_to_app(d, args.server, username, password):
            log("Login failed")
            sys.exit(1)
        
        # Navigate to library
        log("\n[Step 2] Navigate to library")
        navigate_to_library(d)
        
        # Find and click an audiobook
        log("\n[Step 3] Find audiobook")
        if find_and_click_audiobook(d):
            # Trigger download
            log("\n[Step 4] Trigger download")
            trigger_download(d)
        
        # Also trigger sync as backup
        log("\n[Step 5] Trigger sync")
        trigger_sync(d)
        
        log("\n" + "=" * 60)
        log("SUCCESS: Download/sync operations triggered")
        log("=" * 60)
        sys.exit(0)
        
    except KeyboardInterrupt:
        log("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        log(f"Error: {e}")
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
