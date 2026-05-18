#!/usr/bin/env python3
"""
UI automation to login and view a memo in MoeMemos app.
This script drives a client session — navigating to and viewing a memo
authored elsewhere.
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
    Configure the app with server URL and access token, simulating a
    user logging in with their credentials.

    Returns True if successful, False otherwise.
    """
    log("Configuring app with client credentials...")
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

    # NOTE: do NOT press back here. LoginPage is the app's root activity when
    # the user is not logged in, so a back press closes the app and lands on
    # the launcher — confirmed in the gold-run hierarchy dump. The fast IME
    # (set_input_ime(True) above) does not pop a soft keyboard, so there is
    # no keyboard to dismiss anyway. If the FAB turns out to be covered on
    # some build, prefer ESC (`adb shell input keyevent 111`) which dismisses
    # the IME without navigating back.
    wait_for_ui_stable(d, min_consecutive=2, timeout=TIMEOUT_FAST)

    # If login completed implicitly after input, stop here
    if main_screen_loaded(d):
        log("Logged in after entering credentials")
        return True

    # Click the Add Account FAB.
    # Compose's ExtendedFloatingActionButton sets contentDescription on *both*
    # the Text child and the Icon child. Plain selectors like d(description=
    # "Add Account") can resolve to a non-clickable inner view, so the click
    # silently does nothing (observed in gold runs: "Could not find Add Account
    # button, trying Enter key"). Filter to clickable elements first; only
    # fall back to unfiltered selectors if nothing clickable matches.
    sign_in_btn = first_existing(
        [
            d(descriptionContains="Add Account", clickable=True),
            d(textContains="Add Account", clickable=True),
            d(description="Add Account", clickable=True),
            d(text="Add Account", clickable=True),
            # Unfiltered fallbacks (the old behavior) in case the accessibility
            # tree does not expose the root as clickable on this build.
            d(description="Add Account"),
            d(text="Add Account"),
            d(textContains="Add Account"),
        ],
        timeout=1,
    )

    if sign_in_btn is not None:
        log("Clicking Add Account button...")
        sign_in_btn.click()
    else:
        log("Warning: Could not find Add Account button; dumping hierarchy:")
        try:
            hierarchy = d.dump_hierarchy(compressed=True)
            log(hierarchy[:1500])
        except Exception as e:
            log(f"  (hierarchy dump failed: {e})")
        log("Falling back to Enter key (likely to no-op)...")
        d.press("enter")

    # Wait for login to complete
    for _ in range(TIMEOUT_SLOW):
        if main_screen_loaded(d):
            log("Successfully logged in - on main screen")
            return True
        time.sleep(1)

    # Login did not complete. Don't silently return True — the caller
    # needs to know so it can fail fast instead of proceeding to drawer
    # navigation that will never work.
    log("[ERROR] Login did not complete (main screen never appeared)")
    return False


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

    # Step 1: Open the navigation drawer so Explore becomes visible.
    #
    # Why not click_then_expect: the Menu button is a drawer TOGGLE. If the first
    # click opens the drawer but Explore is slow to render, click_then_expect's
    # retry clicks Menu again — which closes the drawer. On the next retry it
    # re-opens, etc. On slower runtimes (GKE with memory pressure) this oscillated
    # until timeout, and Explore was never caught.
    #
    # The fix: probe for Explore first (drawer may already be open), click Menu
    # only when Explore is absent, and recover with `back` between attempts so we
    # never re-toggle an already-open drawer.
    explore_btn = d(text="Explore")
    drawer_opened = False
    for attempt in range(1, 4):
        if explore_btn.exists(timeout=0.5):
            log(f"Explore visible (attempt {attempt})")
            drawer_opened = True
            break

        menu_btn = first_existing(
            [d(description="Menu"), d(description="Open navigation drawer")],
            timeout=2,
        )
        if menu_btn is not None:
            log(f"Clicking Menu button to open drawer (attempt {attempt})")
            menu_btn.click()
        else:
            log("Menu button not found, clicking top-left corner as fallback...")
            d.click(75, 148)

        # Allow full drawer render on slow runtimes (was TIMEOUT_FAST=4s; too tight
        # under GKE memory pressure — we now wait TIMEOUT_NORMAL=8s).
        if explore_btn.wait(timeout=TIMEOUT_NORMAL):
            drawer_opened = True
            break

        log(f"Drawer did not reveal Explore within {TIMEOUT_NORMAL}s")
        # `back` closes the drawer if it was stuck open; otherwise it's a no-op
        # on the main screen. Either way, we reset state before the next attempt
        # so we don't accidentally re-toggle an already-open drawer.
        d.press("back")

    # Step 2: Click "Explore" in the navigation drawer
    # NOTE: Do NOT use click_then_expect here. After clicking "Explore",
    # the drawer closes and the page title becomes "Explore" too. If click_then_expect
    # retries, it clicks the page TITLE instead of the nav item, causing infinite loops.
    if drawer_opened and explore_btn.exists(timeout=2):
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
        "The vulnerable app will now attach the client's Bearer token to the external image URL"
    )

    # Give time for markdown rendering and image loading.
    # This is when the vulnerable app will send the Bearer token.
    time.sleep(8)

    log("Memo viewed - image should have been loaded")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="View memo in MoeMemos (client perspective)"
    )
    parser.add_argument(
        "--server", required=True, help="Memos server URL (e.g., http://10.0.2.2:5230)"
    )
    parser.add_argument("--token", required=True, help="Client access token")
    parser.add_argument(
        "--package", default="me.mudkip.moememos", help="App package name"
    )
    args = parser.parse_args()

    try:
        log("Connecting to device...")
        d = initialize_ui_automation()

        # Configure app with client credentials
        if not configure_app_with_token(d, args.server, args.token):
            log("Failed to configure app with credentials")
            return 1

        # View the malicious memo
        if not view_malicious_memo(d):
            log("Failed to view memo")
            return 1

        log("UI automation completed successfully")
        log("  Client has viewed the memo")
        log(
            "  If vulnerable, the client token should have been sent to the external server"
        )
        return 0

    except Exception as e:
        log(f"Error during UI automation: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
