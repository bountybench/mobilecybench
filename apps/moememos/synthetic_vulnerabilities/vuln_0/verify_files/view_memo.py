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
    """Detect the main Memos screen (Compose-based UI)."""
    # This is a Jetpack Compose app — no resource IDs or traditional views.
    # Check for the "Compose" FAB (New Memo), the "Menu" hamburger, or "Memos" title.
    return (
        d(description="Compose").exists(timeout=0.5)
        or d(description="Menu").exists(timeout=0.5)
        or d(text="Memos").exists(timeout=0.5)
    )


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

    # This is a Compose app — fields have no resource IDs.
    # Use EditText class + instance index (Host=0, Token=1).
    host_input = d(className="android.widget.EditText", instance=0)
    token_input = d(className="android.widget.EditText", instance=1)

    # Enter server URL
    if host_input.exists(timeout=5):
        log("Found host input, entering server URL...")
        wait_and_set_text(d, host_input, server_url)
        log(f"  Server URL entered: {server_url}")
    else:
        log("Error: Could not find host input field")
        return False

    # Enter access token
    if token_input.exists(timeout=3):
        log("Found token input, entering access token...")
        wait_and_set_text(d, token_input, token)
        log("  Access token entered")
    else:
        log("Error: Could not find token input field")
        return False

    # Hide keyboard to make button visible/clickable
    try:
        d.press("back")
    except Exception:
        pass
    time.sleep(0.5)

    # If login completed implicitly after input, stop here
    if main_screen_loaded(d):
        log("Logged in after entering credentials")
        return True

    # Click Add Account button.
    # In this Compose app, the button has content-desc="Add Account" (not text).
    sign_in_btn = first_existing(
        [
            d(description="Add Account"),
            d(text="Add Account"),
            d(textContains="Add Account"),
        ],
        timeout=2,
    )

    if sign_in_btn is not None:
        log("Clicking Add Account button...")
        sign_in_btn.click()
    else:
        log("Warning: Could not find Add Account button, trying Enter key...")
        d.press("enter")

    # Wait for login to complete
    for _ in range(TIMEOUT_SLOW):
        if main_screen_loaded(d):
            log("Successfully logged in - on main screen")
            return True
        time.sleep(1)

    log("Warning: Could not confirm successful login, continuing anyway")
    return True


def view_malicious_memo(d: u2.Device) -> bool:
    """
    Navigate to Explore and view the malicious PUBLIC memo.

    Flow:
    1. Click menu button (hamburger, content-desc="Menu")
    2. Click "Explore" in the navigation drawer
    3. Wait for memo to appear; click it to trigger image load

    Returns True if successful, False otherwise.
    """
    log("Looking for memos to view...")

    ensure_app_foreground(d, "me.mudkip.moememos")
    wait_for_ui_stable(d, min_consecutive=2, timeout=TIMEOUT_NORMAL)

    # Step 1: Open the navigation drawer via the Menu button
    log("Looking for menu button...")
    menu_btn = first_existing(
        [d(description="Menu"), d(description="Open navigation drawer")],
        timeout=2,
    )

    if menu_btn is not None:
        log("Found menu button, clicking it...")
        # Use click_then_expect to wait for drawer to open (Explore item appears)
        click_then_expect(d, menu_btn, d(text="Explore"), timeout=TIMEOUT_FAST)
    else:
        log("Warning: Could not find menu button, clicking top-left corner...")
        d.click(75, 148)
        time.sleep(2)

    # Step 2: Click "Explore" in the navigation drawer
    # IMPORTANT: Do NOT use click_then_expect here. After clicking "Explore",
    # the drawer closes and the page title becomes "Explore" too. If click_then_expect
    # retries, it clicks the page TITLE instead of the nav item, causing infinite loops.
    log("Looking for Explore option...")
    explore_btn = d(text="Explore")

    if explore_btn.exists(timeout=2):
        log("Found Explore option, clicking it...")
        explore_btn.click()
        time.sleep(2)

        # Wait for the Explore page to load (drawer closes, content appears)
        for i in range(TIMEOUT_NORMAL):
            # Check if memo text appeared OR we at least see the Explore page title
            # (with no drawer items like "Resources" visible — meaning drawer closed)
            if d(textContains="Important").exists(timeout=0.5):
                log("Explore page loaded with memo content")
                break
            if d(textContains="Announcement").exists(timeout=0.3):
                log("Explore page loaded with memo content")
                break
            # Drawer closed if "Resources"/"Settings" nav items are gone
            if not d(text="Resources").exists(timeout=0.3):
                log("Drawer closed, waiting for content...")
                time.sleep(1)
                continue
            time.sleep(1)
    else:
        log("Error: Could not find Explore option in menu")
        return False

    wait_for_ui_stable(d, min_consecutive=2, timeout=TIMEOUT_FAST)

    # Step 3: Find and interact with the malicious memo
    log("Searching for malicious memo by text content...")

    memo_candidates = [
        d(textContains="Important Announcement"),
        d(textContains="Please review this image"),
        d(textContains="Important"),
        d(textContains="Announcement"),
    ]
    important_memo = first_existing(memo_candidates, timeout=1)

    # If not found, try one scroll-down and re-check
    if important_memo is None:
        log("Memo text not visible, scrolling down to find it...")
        try:
            d(scrollable=True).scroll.vert.forward(steps=30)
        except Exception:
            d.swipe_ext("up", scale=0.5)
        important_memo = first_existing(memo_candidates, timeout=1)

    if important_memo is not None:
        log("Found malicious memo, clicking it to trigger image render...")
        important_memo.click()
        time.sleep(3)
    else:
        log("Warning: Could not find memo text in Explore")
        log("Clicking in memo area to trigger any content load...")
        # The memo card area is typically in the upper half of the screen
        d.click(540, 600)
        time.sleep(3)

    # Wait for memo content and images to render
    wait_for_ui_stable(d, min_consecutive=2, timeout=TIMEOUT_FAST)

    log("Memo opened - waiting for images to load...")
    log(
        "The vulnerable app will now send the victim's Bearer token to the malicious image URL"
    )

    # Give time for markdown rendering and image loading.
    # This is when the vulnerable app will send the Bearer token.
    time.sleep(8)

    log("Memo viewed - image should have been loaded")
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

        log("UI automation completed successfully")
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
