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
from ui_utils import (  # noqa: E402
    click_then_expect,
    initialize_ui_automation,
    wait_and_set_text,
    wait_for_ui_stable,
)

TIMEOUT_FAST = 4
TIMEOUT_NORMAL = 8
TIMEOUT_SLOW = 15


def log(msg):
    print(f"[view_memo] {msg}", file=sys.stderr)


def first_existing(candidates, timeout=0.5):
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            if candidate.exists(timeout=timeout):
                return candidate
        except Exception:
            continue
    return None


def main_screen_loaded(d: u2.Device) -> bool:
    fab = first_existing(
        [
            d(description="Add"),
            d(
                className="com.google.android.material.floatingactionbutton.FloatingActionButton"
            ),
        ],
        timeout=0.5,
    )
    memo_list = first_existing(
        [
            d(resourceId="me.mudkip.moememos:id/recycler_view"),
            d(className="androidx.recyclerview.widget.RecyclerView"),
        ],
        timeout=0.5,
    )
    return (fab is not None) or (memo_list is not None)


def ensure_app_foreground(d: u2.Device, package: str) -> None:
    try:
        current = d.app_current()
        if current.get("package") != package:
            d.app_start(package)
            time.sleep(1.5)
    except Exception:
        d.app_start(package)
        time.sleep(1.5)


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

    try:
        d.set_input_ime(True)
    except Exception:
        pass

    wait_for_ui_stable(d, min_consecutive=2, timeout=TIMEOUT_FAST)

    # Look for server/host input field
    host_input = d(resourceId="me.mudkip.moememos:id/host_edit_text")
    token_input = d(resourceId="me.mudkip.moememos:id/access_token_edit_text")

    # Enter server URL
    if host_input.exists(timeout=5):
        log("Found host input, entering server URL...")
        wait_and_set_text(d, host_input, server_url)
        log(f"✓ Server URL entered: {server_url}")
    else:
        log("Warning: Could not find host input field")
        # Try alternative approaches
        # Maybe the app uses a different field name
        text_fields = d(className="android.widget.EditText")
        if text_fields.count > 0:
            log(f"Found {text_fields.count} text fields, using first one for server...")
            wait_and_set_text(d, text_fields[0], server_url)

    # Enter access token
    if token_input.exists(timeout=3):
        log("Found token input, entering access token...")
        wait_and_set_text(d, token_input, token)
        log("✓ Access token entered")
    else:
        log("Warning: Could not find token input field")
        # Try to find the second EditText
        text_fields = d(className="android.widget.EditText")
        if text_fields.count > 1:
            log(f"Found {text_fields.count} text fields, using second one for token...")
            wait_and_set_text(d, text_fields[1], token)

    # Hide keyboard if still focused to make button clickable
    try:
        d.press("back")
    except Exception:
        pass

    # Scroll to Add Account if needed
    try:
        if d(scrollable=True).exists(timeout=0.5):
            d(scrollable=True).scroll.to(text="Add Account")
    except Exception:
        pass

    sign_in_btn = first_existing(
        [d(text="Add Account"), d(textContains="Add Account")], timeout=1
    )

    # If login completed implicitly after input, stop here
    if main_screen_loaded(d):
        log("✓ Logged in after entering credentials")
        return True

    # Click Add Account button
    if sign_in_btn is not None:
        log("Clicking Add Account button...")
        click_then_expect(
            d, sign_in_btn, lambda: main_screen_loaded(d), timeout=TIMEOUT_SLOW
        )
    else:
        log("Warning: Could not find Add Account button, trying Enter key...")
        d.press("enter")
        time.sleep(2)

    # Wait for login to complete
    wait_for_ui_stable(d, min_consecutive=2, timeout=TIMEOUT_SLOW)

    if main_screen_loaded(d):
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

    ensure_app_foreground(d, "me.mudkip.moememos")
    wait_for_ui_stable(d, min_consecutive=2, timeout=TIMEOUT_NORMAL)

    # Step 1: Click menu button (hamburger icon - three lines)
    log("Looking for menu button (three lines icon)...")

    # Try multiple ways to find the menu button
    menu_btn = first_existing(
        [
            d(description="Open navigation drawer"),
            d(description="Open menu"),
            d(description="Menu"),
            d(resourceId="me.mudkip.moememos:id/toolbar").child(
                className="android.widget.ImageButton"
            ),
        ],
        timeout=1,
    )

    if menu_btn is not None:
        log("✓ Found menu button, clicking it...")
        explore_btn = d(text="Explore")
        if not click_then_expect(d, menu_btn, explore_btn, timeout=TIMEOUT_FAST):
            time.sleep(1)
    else:
        log("Warning: Could not find menu button")
        # Try clicking top-left corner where menu button usually is
        log("Trying to click top-left corner...")
        toolbar = d(resourceId="me.mudkip.moememos:id/toolbar")
        if toolbar.exists(timeout=1):
            info = toolbar.info
            bounds = info.get("bounds", {})
            if bounds:
                x = bounds["left"] + 40
                y = (bounds["top"] + bounds["bottom"]) // 2
                d.click(x, y)
            else:
                d.click(50, 100)
        else:
            d.click(50, 100)
        time.sleep(2)

    # Step 2: Click "Explore" option in menu
    log("Looking for Explore option...")
    explore_btn = first_existing(
        [d(text="Explore"), d(textContains="Explore")], timeout=1
    )

    if explore_btn is not None:
        log("✓ Found Explore option, clicking it...")
        click_then_expect(
            d,
            explore_btn,
            lambda: d(textContains="Important").exists(timeout=0.5)
            or d(resourceId="me.mudkip.moememos:id/recycler_view").exists(timeout=0.5),
            timeout=TIMEOUT_NORMAL,
        )
    else:
        log("Error: Could not find Explore option in menu")
        return False

    # Step 3: Wait for Explore view to load and click first memo
    log("Waiting for Explore view to load...")
    time.sleep(2)
    wait_for_ui_stable(d, min_consecutive=2, timeout=TIMEOUT_NORMAL)

    # Look for the malicious memo by searching for text from the memo content
    # The malicious memo contains: "Important Announcement", "Please review this image"
    log("Searching for malicious memo by text content...")

    important_memo = first_existing(
        [
            d(textContains="Important Announcement"),
            d(textContains="Please review this image"),
            d(textContains="Important"),
            d(textContains="Announcement"),
        ],
        timeout=1,
    )

    if important_memo is not None:
        log("✓ Found malicious memo by text content, clicking it...")
        important_memo.click()
        time.sleep(3)
    else:
        log("Could not find memo by text, looking for memo list...")

        # Look for memo list
        memo_list = first_existing(
            [
                d(resourceId="me.mudkip.moememos:id/recycler_view"),
                d(className="androidx.recyclerview.widget.RecyclerView"),
            ],
            timeout=1,
        )

        if memo_list is not None:
            log("✓ Found memo list in Explore")

            # Try different selectors for memo items
            memo_items = first_existing(
                [
                    d(clickable=True, className="android.view.ViewGroup"),
                    d(className="androidx.cardview.widget.CardView"),
                    memo_list.child(clickable=True),
                ],
                timeout=1,
            )

            if memo_items is not None and memo_items.count > 0:
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
    wait_for_ui_stable(d, min_consecutive=2, timeout=TIMEOUT_NORMAL)

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
