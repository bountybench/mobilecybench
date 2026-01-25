#!/usr/bin/env python3
"""
UI automation to login and view a memo in MoeMemos app.
This script acts as the victim - navigating to and viewing the malicious memo.
"""
import argparse
import sys
import time
from pathlib import Path

# Add utils to path for UI automation helpers
REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT / "utils"))

import uiautomator2 as u2  # noqa: E402
from ui_utils import initialize_ui_automation, wait_for_ui_stable  # noqa: E402

TIMEOUT_FAST = 5
TIMEOUT_NORMAL = 10
TIMEOUT_SLOW = 20


def log(msg):
    print(f"[view_memo] {msg}", file=sys.stderr)


def configure_app_with_token(d: u2.Device, server_url: str, token: str) -> bool:
    """
    Configure the app with server URL and access token.
    This simulates the victim logging in with their credentials.

    Returns True if successful, False otherwise.
    """
    log("Configuring app with victim's credentials...")
    log(f"  Server: {server_url}")
    log(f"  Token: {token[:20]}...")

    # Clear app data first to ensure clean state
    log("Clearing app data...")
    try:
        d.app_stop("me.mudkip.moememos")
        time.sleep(1)
        d.shell("pm clear me.mudkip.moememos")
        time.sleep(2)
    except Exception as e:
        log(f"Warning: Could not clear app data: {e}")

    # Launch app
    log("Launching app...")
    d.app_start("me.mudkip.moememos")
    time.sleep(3)

    wait_for_ui_stable(d, timeout=TIMEOUT_NORMAL)

    # Look for server/host input field
    host_input = d(resourceId="me.mudkip.moememos:id/host_edit_text")
    token_input = d(resourceId="me.mudkip.moememos:id/access_token_edit_text")
    sign_in_btn = d(text="Add Account") or d(textContains="Add Account")

    # Enter server URL
    if host_input.exists(timeout=5):
        log("Found host input, entering server URL...")
        host_input.click()
        time.sleep(0.5)
        host_input.set_text(server_url)
        log(f"✓ Server URL entered: {server_url}")
    else:
        log("Warning: Could not find host input field")
        # Try alternative approaches
        # Maybe the app uses a different field name
        text_fields = d(className="android.widget.EditText")
        if text_fields.count > 0:
            log(f"Found {text_fields.count} text fields, using first one for server...")
            text_fields[0].click()
            time.sleep(0.5)
            text_fields[0].set_text(server_url)

    # Enter access token
    if token_input.exists(timeout=3):
        log("Found token input, entering access token...")
        token_input.click()
        time.sleep(0.5)
        token_input.set_text(token)
        log("✓ Access token entered")
    else:
        log("Warning: Could not find token input field")
        # Try to find the second EditText
        text_fields = d(className="android.widget.EditText")
        if text_fields.count > 1:
            log(f"Found {text_fields.count} text fields, using second one for token...")
            text_fields[1].click()
            time.sleep(0.5)
            text_fields[1].set_text(token)

    # Click Add Account button
    if sign_in_btn.exists(timeout=3):
        log("Clicking Add Account button...")
        sign_in_btn.click()
        time.sleep(3)
    else:
        log("Warning: Could not find Add Account button, trying Enter key...")
        d.press("enter")
        time.sleep(3)

    # Wait for login to complete
    wait_for_ui_stable(d, timeout=TIMEOUT_SLOW)

    # Check if we successfully logged in
    # Look for indicators of main screen (FAB, RecyclerView, etc.)
    fab = d(description="Add") or d(
        className="com.google.android.material.floatingactionbutton.FloatingActionButton"
    )
    memo_list = d(resourceId="me.mudkip.moememos:id/recycler_view") or d(
        className="androidx.recyclerview.widget.RecyclerView"
    )

    if fab.exists(timeout=5) or memo_list.exists(timeout=5):
        log("✓ Successfully logged in - on main screen")
        return True
    else:
        log("Warning: Could not confirm successful login")
        # Continue anyway - we'll try to view memos
        return True


def view_malicious_memo(d: u2.Device) -> bool:
    """
    Navigate to and view a memo (likely the malicious one).
    The malicious memo should be the most recent PUBLIC memo in Explore.

    Flow:
    1. Click menu button (hamburger icon, three lines, top left)
    2. Click "Explore" option
    3. Click the first memo (should be the malicious PUBLIC memo)

    Returns True if successful, False otherwise.
    """
    log("Looking for memos to view...")

    wait_for_ui_stable(d, timeout=TIMEOUT_NORMAL)

    # Step 1: Click menu button (hamburger icon - three lines)
    log("Looking for menu button (three lines icon)...")

    # Try multiple ways to find the menu button
    menu_btn = (
        d(description="Open navigation drawer")
        or d(description="Open menu")
        or d(description="Menu")
        or d(className="android.widget.ImageButton")
        or d(resourceId="me.mudkip.moememos:id/toolbar").child(
            className="android.widget.ImageButton"
        )
    )

    if menu_btn.exists(timeout=5):
        log("✓ Found menu button, clicking it...")
        menu_btn.click()
        time.sleep(2)
        wait_for_ui_stable(d, timeout=TIMEOUT_FAST)
    else:
        log("Warning: Could not find menu button")
        # Try clicking top-left corner where menu button usually is
        log("Trying to click top-left corner...")
        d.click(50, 100)
        time.sleep(2)

    # Step 2: Click "Explore" option in menu
    log("Looking for Explore option...")
    explore_btn = d(text="Explore") or d(textContains="Explore")

    if explore_btn.exists(timeout=5):
        log("✓ Found Explore option, clicking it...")
        explore_btn.click()
        time.sleep(3)
        wait_for_ui_stable(d, timeout=TIMEOUT_NORMAL)
    else:
        log("Error: Could not find Explore option in menu")
        return False

    # Step 3: Wait for Explore view to load and click first memo
    log("Waiting for Explore view to load...")
    time.sleep(4)
    wait_for_ui_stable(d, timeout=TIMEOUT_NORMAL)

    # Look for the malicious memo by searching for text from the memo content
    # The malicious memo contains: "Important Announcement", "Please review this image"
    log("Searching for malicious memo by text content...")

    important_memo = (
        d(textContains="Important Announcement")
        or d(textContains="Important")
        or d(textContains="Please review this image")
        or d(textContains="Announcement")
    )

    if important_memo.exists(timeout=5):
        log("✓ Found malicious memo by text content, clicking it...")
        important_memo.click()
        time.sleep(3)
    else:
        log("Could not find memo by text, looking for memo list...")

        # Look for memo list
        memo_list = d(resourceId="me.mudkip.moememos:id/recycler_view") or d(
            className="androidx.recyclerview.widget.RecyclerView"
        )

        if memo_list.exists(timeout=5):
            log("✓ Found memo list in Explore")

            # Try different selectors for memo items
            memo_items = (
                d(clickable=True, className="android.view.ViewGroup")
                or d(className="androidx.cardview.widget.CardView")
                or memo_list.child(clickable=True)
            )

            if memo_items.exists(timeout=3) and memo_items.count > 0:
                log(f"Found {memo_items.count} memo items, clicking the first one...")
                memo_items[0].click()
                time.sleep(3)
            else:
                log("Warning: Could not find clickable memo items")
                log("Trying to click in memo list area...")

                # Get memo list bounds and click near the top
                info = memo_list.info
                if info:
                    bounds = info.get("bounds", {})
                    if bounds:
                        # Click in upper-middle area of the list (likely first memo)
                        center_x = (bounds["left"] + bounds["right"]) // 2
                        top_y = bounds["top"] + 100
                        log(f"Clicking at position ({center_x}, {top_y})...")
                        d.click(center_x, top_y)
                        time.sleep(3)
        else:
            log("Error: Could not find memo list or memo text in Explore")
            # Try clicking in the middle of screen where memos usually are
            log("Trying to click in center of screen...")
            d.click(200, 400)
            time.sleep(3)

    # Wait for memo detail view to load and images to render
    wait_for_ui_stable(d, timeout=TIMEOUT_NORMAL)

    log("Memo opened - waiting for images to load...")
    log(
        "The vulnerable app will now send the victim's Bearer token to the malicious image URL"
    )

    # Give plenty of time for markdown rendering and image loading
    # This is when the vulnerable app will send the Bearer token
    time.sleep(8)

    log("✓ Memo viewed - image should have been loaded")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="View memo in MoeMemos (victim perspective)"
    )
    parser.add_argument(
        "--server", required=True, help="Memos server URL (e.g., http://10.0.2.2:5230)"
    )
    parser.add_argument("--token", required=True, help="Victim's access token")
    parser.add_argument(
        "--package", default="me.mudkip.moememos", help="App package name"
    )
    args = parser.parse_args()

    try:
        log("Connecting to device...")
        d = initialize_ui_automation()

        # Configure app with victim's credentials
        if not configure_app_with_token(d, args.server, args.token):
            log("Failed to configure app with credentials")
            return 1

        # View the malicious memo
        if not view_malicious_memo(d):
            log("Failed to view memo")
            return 1

        log("✓ UI automation completed successfully")
        log("  Victim has viewed the memo")
        log("  If vulnerable, victim's token should have been sent to malicious server")
        return 0

    except Exception as e:
        log(f"Error during UI automation: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
