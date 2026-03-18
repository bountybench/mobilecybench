"""
A collection of helpers for Android UI automation using uiautomator2.

This module provides an API for common UI interactions like finding elements,
clicking, and setting text, with built-in handling for ANRs and UI instability.

PREFERRED FUNCTIONS (use these for new code):
- click_then_expect(): Click and verify expected element appears (with retries)
- press_back_then_expect(): Press back and verify expected screen
- wait_for_screen_change(): Detect that UI changed after an action
- wait_for_ui_stable(): Wait for UI to stop changing

LEGACY FUNCTIONS (still work, but less robust for new code):
- wait_and_click(): Clicks but doesn't verify what appears after
  → Use click_then_expect() instead when you know what should appear

MIGRATION STATUS (apps that need updating to preferred functions):
- bitwarden: bw_workflows.py, create_accounts.py, test_availability.py, test_access_control.py
- grocy: setup_grocy_ui.py (uses uiautomator2 directly, should migrate to shared utils)
- linphone: synch_app.py (uses uiautomator2 directly)
- audiobookshelf: synch_app.py (uses uiautomator2 directly)
"""

import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, NoReturn, Optional, Union

import uiautomator2 as u2
from uiautomator2 import Device, UiObject

__all__ = [
    "initialize_ui_automation",
    "wait_and_click",
    "wait_and_set_text",
    "wait_for_ui_stable",
    "wait_for_screen_change",
    "click_then_expect",
    "press_back_then_expect",
]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ANDROID_READY_SCRIPT = PROJECT_ROOT / "utils" / "android_emulator_ready.sh"

# Target Android package name for UI automation. Must be set via UI_TARGET_PACKAGE env var.
# If unset, TARGET_PACKAGE becomes None.
TARGET_PACKAGE = os.getenv("UI_TARGET_PACKAGE")

UI_RETRIES = 5  # Default number of retries for fallible operations
RETRY_INTERVAL = 1  # Default seconds to wait between retries

MAX_ANRS = 5  # Max ANR dialogs to dismiss before failing
MAX_SCROLLS = 5  # Max scrolls to perform when searching for an element

CLICK_TIMEOUT = 3  # Seconds to wait for a click to register
SHORT_TIMEOUT = 10  # Short timeout for non-critical waits
MAX_TIMEOUT = 180  # Long timeout for critical waits (e.g., finding an element)

logger = logging.getLogger("mobilecybench.ui")
logger.setLevel("DEBUG")
_handler = logging.StreamHandler(stream=sys.stderr)
_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
if not logger.handlers:
    logger.addHandler(_handler)

# =============================================================================
# UI AUTOMATION INITIALIZATION
# =============================================================================


def initialize_ui_automation(
    max_retries: int = UI_RETRIES, retry_delay: int = RETRY_INTERVAL
) -> Device:
    """Connect to a device with uiautomator2."""
    try:
        _preflight_emulator_readiness()
    except Exception as e:
        logger.warning("Readiness preflight script failed: %s.", e)

    for attempt_index in range(1, max_retries + 1):
        logger.info("Connecting to device (attempt %s/%s)…", attempt_index, max_retries)

        try:
            logger.debug("Attempting to connect uiautomator2 client...")
            device = u2.connect()
            logger.info("Connected to device.")

            return device

        except Exception as e:
            logger.info("Connection failed: %s", e)
            if attempt_index < max_retries:
                time.sleep(retry_delay)
                continue
            _fatal(
                None,
                f"Failed to connect to device after {max_retries} attempts: {e}",
            )


# =============================================================================
# PUBLIC UI ELEMENT INTERACTION FUNCTIONS
# =============================================================================


def wait_and_click(d: Device, element: UiObject, timeout: int = MAX_TIMEOUT) -> bool:
    """Wait for an element and click it with retries for stale object errors."""
    _ensure_target_app_foreground(d)

    if not _wait_for_element(d, element, timeout=timeout):
        app_state = d.app_current()
        current_pkg = app_state.get("package", "unknown")
        current_activity = app_state.get("activity", "unknown")
        message = (
            f"Could not find element: '{element.selector}' within {timeout}s.\n"
            f"  - Current screen: {current_pkg}/{current_activity}."
        )
        _fatal(d, message)

    else:
        logger.debug("Found element %s", element.selector)

    for attempt_index in range(1, UI_RETRIES + 1):
        try:
            if element.click_exists(timeout=CLICK_TIMEOUT):
                logger.info(
                    "Clicked element %s on attempt %s", element.selector, attempt_index
                )
                wait_for_ui_stable(d)
                return True
            # Element is present but not clickable (timeout exceeded)
            raise TimeoutError("click timeout")

        except Exception as e:
            if isinstance(e, TimeoutError):
                logger.debug(
                    "Click failed due to timeout (not clickable) (attempt %s/%s) for %s",
                    attempt_index,
                    UI_RETRIES,
                    element.selector,
                )
            elif "StaleObjectException" in e:
                logger.debug(
                    "Click failed due to stale object (attempt %s/%s) for %s: %s",
                    attempt_index,
                    UI_RETRIES,
                    element.selector,
                    e,
                )
            else:
                logger.debug(
                    "Click failed due to unknown error (attempt %s/%s) for %s: %s",
                    attempt_index,
                    UI_RETRIES,
                    element.selector,
                    e,
                )

            if attempt_index < UI_RETRIES:
                logger.debug(
                    "Retrying click for %s (attempt %s/%s): %s",
                    element.selector,
                    attempt_index,
                    UI_RETRIES,
                    e,
                )
                wait_for_ui_stable(d)
                time.sleep(RETRY_INTERVAL)
                continue

            _fatal(
                d,
                f"Failed to click element '{element.selector}' after {UI_RETRIES} attempts",
            )


def wait_and_set_text(
    d: Device,
    element: UiObject,
    text: str,
    max_retries: int = UI_RETRIES,
    retry_delay: int = RETRY_INTERVAL,
) -> bool:
    """Focus the input by clicking it, set text, then finalize IME action."""
    # Use wait_and_click to focus the field first
    clicked = wait_and_click(d, element)
    if not clicked:
        return False

    for attempt_index in range(1, max_retries + 1):
        try:
            if not element.exists:
                _ensure_target_app_foreground(d)
                _wait_for_element(d, element)

            element.set_text(text)
            logger.debug("Set text on attempt %s.", attempt_index)
            logger.info("Set text to %s", text)

            wait_for_ui_stable(d)
            return True

        except Exception as e:
            logger.debug("Set text failed on attempt %s: %s", attempt_index, e)
            if attempt_index < max_retries:
                time.sleep(retry_delay)
            else:
                message = f"Failed to set text on element: '{element.selector}' after {max_retries} attempts"
                _fatal(d, message)


def wait_for_ui_stable(
    d: Device,
    min_consecutive: int = 5,
    retry_delay: int = RETRY_INTERVAL,
    timeout: int = SHORT_TIMEOUT,
) -> bool:
    """Wait for the UI to stabilize by checking consecutive identical hierarchy dumps."""
    prev_dump = None
    same_count = 0
    start = time.time()

    while time.time() - start < timeout:
        try:
            current_dump = d.dump_hierarchy()
        except Exception as e:
            app_state = d.app_current()
            current_pkg = app_state.get("package")
            current_activity = app_state.get("activity")

            if _is_launcher_activity(current_pkg, current_activity):
                logger.debug(
                    "Launcher detected in foreground (%s/%s); aborting element wait. UI cannot become stable.",
                    current_pkg,
                    current_activity,
                )
                return False

            else:
                logger.debug(
                    "Failed to get hierarchy dump during stability check: %s", e
                )

            time.sleep(retry_delay)
            continue

        # Count consecutive identical dumps
        if prev_dump is not None and current_dump == prev_dump:
            same_count += 1
        else:
            same_count = 1

        prev_dump = current_dump

        # Return True if the UI has stabilized for at least min_consecutive samples
        if same_count >= min_consecutive:
            logger.debug("UI stabilized (hierarchy dump) in %.1fs", time.time() - start)
            return True

        # Wait for some time to avoid false positive before screen transitions
        time.sleep(retry_delay)

    logger.warning(
        "UI did not stabilize (hierarchy dump) within %.1fs (required %s consecutive identical samples).",
        time.time() - start,
        min_consecutive,
    )
    return False


def wait_for_screen_change(
    d: Device,
    original_hierarchy: str,
    timeout: float = 2.0,
    interval: float = 0.2,
) -> bool:
    """Wait for screen to differ from original state.

    This is useful for detecting that an action (click, back, etc.) had an effect
    on the UI. Capture the hierarchy before the action, then call this function
    to wait until the screen changes.

    Args:
        d: uiautomator2 device instance
        original_hierarchy: UI hierarchy string captured before the action
        timeout: Max wait time in seconds
        interval: Polling interval in seconds

    Returns:
        True if screen changed, False if timeout
    """
    start = time.time()
    while time.time() - start < timeout:
        try:
            current = d.dump_hierarchy(compressed=True)
            if current != original_hierarchy:
                logger.debug("Screen changed after %.2fs", time.time() - start)
                return True
        except Exception as e:
            logger.debug("Failed to dump hierarchy during screen change check: %s", e)
        time.sleep(interval)

    logger.debug("Screen did not change within %.1fs", timeout)
    return False


def click_then_expect(
    d: Device,
    element: UiObject,
    expected: Union[UiObject, Callable[[], bool]],
    timeout: int = SHORT_TIMEOUT,
    retries: int = UI_RETRIES,
) -> bool:
    """Click element and verify expected result appears, with retry logic.

    This function provides robust click handling by:
    1. Verifying element exists before clicking
    2. Capturing screen state before click
    3. Clicking and waiting for screen to change
    4. Waiting for expected element/condition
    5. Retrying if click didn't register

    Use this instead of wait_and_click() when you know what element should
    appear after the click. This provides stronger verification that the
    click had the intended effect.

    Args:
        d: uiautomator2 device instance
        element: The element to click
        expected: Element that should appear after click, OR callable returning True when valid
        timeout: Max wait time per attempt (seconds)
        retries: Number of retry attempts if click doesn't register

    Returns:
        True if click succeeded and expected state reached, False otherwise

    Example:
        # Click menu button and wait for menu item to appear
        menu_btn = d(description="More options")
        menu_item = d(text="Settings")
        if click_then_expect(d, menu_btn, menu_item):
            # Menu opened successfully, now click the menu item
            ...

        # Using a callable for complex conditions
        def settings_screen_loaded():
            return d(text="Settings").exists and d(text="Account").exists
        click_then_expect(d, menu_btn, settings_screen_loaded)
    """
    for attempt in range(1, retries + 1):
        # 1. Verify element exists
        if not element.exists:
            logger.debug(
                "Element %s does not exist (attempt %s/%s)",
                element.selector,
                attempt,
                retries,
            )
            time.sleep(RETRY_INTERVAL)
            continue

        # 2. Check if clickable (warn but proceed - some elements work despite this)
        try:
            info = element.info
            if not info.get("clickable", False):
                logger.debug(
                    "Element %s exists but clickable=False, proceeding anyway",
                    element.selector,
                )
        except Exception:
            pass  # Info fetch failed, proceed anyway

        # 3. Capture screen state before click
        try:
            pre_click_hierarchy = d.dump_hierarchy(compressed=True)
        except Exception as e:
            logger.debug("Failed to capture pre-click hierarchy: %s", e)
            pre_click_hierarchy = None

        # 4. Click
        try:
            element.click()
            logger.debug(
                "Clicked %s (attempt %s/%s)", element.selector, attempt, retries
            )
        except Exception as e:
            logger.debug(
                "Click failed for %s (attempt %s/%s): %s",
                element.selector,
                attempt,
                retries,
                e,
            )
            time.sleep(RETRY_INTERVAL)
            continue

        # 5. Wait for screen to change
        if pre_click_hierarchy is not None:
            changed = wait_for_screen_change(d, pre_click_hierarchy, timeout=2.0)
            if not changed:
                logger.debug(
                    "Screen did not change after clicking %s (attempt %s/%s)",
                    element.selector,
                    attempt,
                    retries,
                )
                continue

        # 6. Wait for expected element/state
        if callable(expected):
            # Custom validation function - poll until true or timeout
            start = time.time()
            while time.time() - start < timeout:
                try:
                    if expected():
                        logger.info(
                            "Click on %s succeeded, expected condition met",
                            element.selector,
                        )
                        return True
                except Exception as e:
                    logger.debug("Expected condition check failed: %s", e)
                time.sleep(RETRY_INTERVAL)
        else:
            # Wait for element selector
            if expected.wait(timeout=timeout):
                logger.info(
                    "Click on %s succeeded, expected element %s appeared",
                    element.selector,
                    expected.selector,
                )
                return True

        logger.debug(
            "Expected state not reached after clicking %s (attempt %s/%s)",
            element.selector,
            attempt,
            retries,
        )

    logger.warning(
        "Click on %s failed after %s attempts - expected state never reached",
        element.selector,
        retries,
    )
    return False


def press_back_then_expect(
    d: Device,
    expected: Union[UiObject, Callable[[], bool]],
    timeout: int = SHORT_TIMEOUT,
) -> bool:
    """Press back button and verify expected screen element appears.

    Use this for navigation where you need to verify you landed on the
    expected screen after pressing back.

    Args:
        d: uiautomator2 device instance
        expected: Element that should appear after back, OR callable returning True when valid
        timeout: Max wait time (seconds)

    Returns:
        True if back succeeded and expected state reached, False otherwise

    Example:
        # Press back and wait for main screen indicator
        main_screen = d(description="More options")
        if press_back_then_expect(d, main_screen):
            # Successfully returned to main screen
            ...
    """
    # Capture screen state before back
    try:
        pre_back_hierarchy = d.dump_hierarchy(compressed=True)
    except Exception as e:
        logger.debug("Failed to capture pre-back hierarchy: %s", e)
        pre_back_hierarchy = None

    # Press back
    d.press("back")
    logger.debug("Pressed back button")

    # Wait for screen to change
    if pre_back_hierarchy is not None:
        changed = wait_for_screen_change(d, pre_back_hierarchy, timeout=2.0)
        if not changed:
            logger.debug("Screen did not change after pressing back")

    # Wait for expected element/state
    if callable(expected):
        start = time.time()
        while time.time() - start < timeout:
            try:
                if expected():
                    logger.debug("Back succeeded, expected condition met")
                    return True
            except Exception as e:
                logger.debug("Expected condition check failed: %s", e)
            time.sleep(RETRY_INTERVAL)
    else:
        if expected.wait(timeout=timeout):
            logger.debug(
                "Back succeeded, expected element %s appeared", expected.selector
            )
            return True

    logger.warning("Back button did not result in expected state")
    return False


# =============================================================================
# PRIVATE U2 INITIALIZATION HELPERS
# =============================================================================


def _preflight_emulator_readiness():
    """Run the android emulator readiness script once; keep stdout silent."""
    try:
        if not ANDROID_READY_SCRIPT.exists():
            logger.debug(
                "Readiness script not found at %s; skipping preflight.",
                ANDROID_READY_SCRIPT,
            )
            return

        logger.info("Running emulator readiness preflight: %s", ANDROID_READY_SCRIPT)
        subprocess.run(
            [str(ANDROID_READY_SCRIPT)], check=True, stdout=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError as e:
        logger.warning("Readiness preflight failed (exit %s); continuing", e.returncode)
    except Exception as e:
        logger.debug("Preflight readiness skipped: %s", e)


# =============================================================================
# PRIVATE UI UTILITY HELPERS
# =============================================================================


def _wait_for_element(
    d: Device,
    element: UiObject,
    max_scrolls: int = MAX_SCROLLS,
    retry_delay: int = RETRY_INTERVAL,
    timeout: int = MAX_TIMEOUT,
) -> bool:
    """Wait for an element; if missing, perform limited coarse scrolls to reveal it."""

    start = time.time()
    try:
        selector_str = str(getattr(element, "selector", element))
    except Exception:
        selector_str = "<unknown>"

    scrolls = 0
    while time.time() - start < timeout:
        # Ensure we're in the intended app before attempting waits/scrolls
        _ensure_target_app_foreground(d)

        if not _handle_anr(d, target_element=element):
            logger.debug("Failed to unfreeze system UI; aborting element wait.")
            return False

        if element.exists:
            logger.debug(
                "Element %s appeared after %.1fs", selector_str, time.time() - start
            )
            return True

        # Scroll forward to try to reveal the element
        try:
            scroller = d(scrollable=True)
            if scroller.exists and scrolls < max_scrolls:
                scrolls += 1
                scroller.scroll.forward()
        except Exception as e:
            logger.warning("Failed to scroll forward: %s", e)

        time.sleep(retry_delay)

    logger.debug("Timed out waiting for %s", selector_str)
    return False


def _is_launcher_activity(
    current_pkg: Optional[str], current_activity: Optional[str]
) -> bool:
    """
    Check if the current foreground activity is a launcher with common launcher package names.
    """
    if not current_pkg and not current_activity:
        return False

    pkg_l = (current_pkg or "").lower()
    act_l = (current_activity or "").lower()

    known_launcher_pkgs = {
        "com.android.launcher",
        "com.android.launcher3",
        "com.google.android.apps.nexuslauncher",
    }

    if pkg_l in known_launcher_pkgs:
        return True

    if "launcher" in pkg_l or "launcher" in act_l:
        return True

    return False


def _ensure_target_app_foreground(d: Device, timeout: int = SHORT_TIMEOUT) -> bool:
    """
    Ensure the target app (from UI_TARGET_PACKAGE) is in the foreground.
    If the launcher or a different app is foreground, attempt to bring the target app to front.
    """
    try:
        app_state = d.app_current()
        current_pkg = app_state.get("package")
        current_activity = app_state.get("activity")

        if not TARGET_PACKAGE:
            return True  # No target package, so no need to bring it to front

        # If launcher is shown or we're on a different app, try to recover
        if _is_launcher_activity(current_pkg, current_activity) or (
            current_pkg and current_pkg != TARGET_PACKAGE
        ):
            logger.info(
                "Incorrect app in foreground (%s). Attempting to restart %s...",
                current_pkg,
                TARGET_PACKAGE,
            )
            try:
                # Force-stop the app before starting to ensure a clean state
                d.app_start(TARGET_PACKAGE, stop=True, wait=True, use_monkey=True)

                # Wait for the app to launch and UI to settle
                if timeout > 0:
                    wait_for_ui_stable(d, timeout=timeout)

                # Verify that the correct app is now in the foreground
                restarted_app_state = d.app_current()
                if restarted_app_state.get("package") == TARGET_PACKAGE:
                    logger.info(
                        "Successfully brought %s to foreground.", TARGET_PACKAGE
                    )
                else:
                    logger.warning(
                        "Failed to bring %s to foreground after restart. Current app: %s",
                        TARGET_PACKAGE,
                        restarted_app_state.get("package"),
                    )

            except Exception as relaunch_err:
                logger.warning(
                    "An error occurred while trying to restart %s: %s",
                    TARGET_PACKAGE,
                    relaunch_err,
                )
        return True

    except Exception as e:
        logger.warning("Failed to ensure target app foreground: %s", e)
        return False


def _handle_anr(
    d: Device,
    max_anrs: int = MAX_ANRS,
    wait_timeout: int = SHORT_TIMEOUT,
    target_element: Optional[UiObject] = None,
) -> bool:
    """Click ANR 'Wait' up to max_anrs times; settle with idle/stable checks."""
    anr_count = 0
    wait_button = d(resourceId="android:id/aerr_wait")

    for _ in range(max_anrs):
        try:
            if wait_button.exists():
                anr_count += 1
                logger.debug(
                    "ANR dialog #%s detected. Clicking 'Wait' to continue...", anr_count
                )
                wait_button.click()

                # Wait for either target element or UI stability
                if target_element is not None:
                    logger.debug(
                        "Waiting for target element '%s' to appear after ANR...",
                        target_element.selector,
                    )
                    if target_element.wait(timeout=wait_timeout):
                        logger.debug(
                            "Target element '%s' appeared successfully after ANR.",
                            target_element.selector,
                        )
                        break  # Target element found - exit ANR loop
                    else:
                        logger.debug(
                            "Target element '%s' did not appear after ANR dismissal.",
                            target_element.selector,
                        )
                        continue  # Continue checking for more ANRs
                else:
                    logger.debug("Waiting for UI to stabilize after ANR...")
                    wait_for_ui_stable(d)
            else:
                return True  # No ANR dialog found
        except Exception as e:
            logger.warning(
                "Could not click ANR 'Wait' button (it may have disappeared): %s", e
            )
            break

    # Reached max ANR limit: log summary and report False (non-fatal)
    if anr_count == max_anrs:
        logger.error(
            "Could not fully handle ANR dialog(s): reached maximum limit of %s.",
            max_anrs,
        )
        return False

    if anr_count > 0:
        logger.info(
            "Handled %s consecutive ANR dialog(s) until system UI unfreeze.", anr_count
        )

    return True


# =============================================================================
# PRIVATE FATAL ERROR HANDLER
# =============================================================================


def _fatal(d: Optional[Device], message: str) -> NoReturn:
    """
    Fatal error handler that logs the error message, raw adb logs, and UI hierarchy.
    """
    logger.critical("%s", message)

    try:
        if d is not None:
            app_state = d.app_current()
            logger.debug("Current package: %s", app_state.get("package"))
            logger.debug("Current activity: %s", app_state.get("activity"))
    except Exception as e:
        logger.warning("Failed to get current app state: %s", e)

    # Output last 100 lines of adb logs
    try:
        subprocess.run(
            ["adb", "logcat", "-t", "100"],
            stdout=sys.stderr,
            timeout=MAX_TIMEOUT,
            check=True,
        )
    except Exception as e:
        logger.warning("Failed to get adb logcat output: %s", e)

    # Dump UI hierarchy
    try:
        if d is not None:
            try:
                logger.critical("%s", d.dump_hierarchy())
            except Exception as dump_err:
                logger.warning("Failed to dump UI hierarchy: %s", dump_err)
                # Raise special exception for accessibility bind race
                if "NullPointerException" in str(dump_err):
                    logger.warning(
                        "Skipped hierarchy dump (NullPointerException): %s", dump_err
                    )
    except Exception as outer:
        logger.warning("Fatal handler encountered an error: %s", outer)

    sys.exit(1)
