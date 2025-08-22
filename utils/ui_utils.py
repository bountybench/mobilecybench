"""
uiautomator2 helpers for reliable clicking and text entry.
Public API: initialize_ui_automation, wait_and_click, wait_and_set_text, wait_for_ui_stable
"""

import logging
import os
import re
import subprocess
import sys
import time

import uiautomator2 as u2

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
logger = logging.getLogger("mobilecybench.ui")
logger.setLevel(os.getenv("UI_LOG_LEVEL", "DEBUG"))
_handler = logging.StreamHandler(stream=sys.stderr)
_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
if not logger.hasHandlers():
    logger.addHandler(_handler)

# =============================================================================
# UI AUTOMATION INITIALIZATION
# =============================================================================


def initialize_ui_automation(max_retries=5, retry_delay=5):
    """Connect to a device and enable sane defaults (implicit waits, no sleeps)."""

    def _adb_has_devices(timeout_seconds: int = 5) -> bool:
        try:
            result = subprocess.run(
                ["adb", "devices"],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            if result.returncode != 0:
                logger.warning("'adb devices' failed: %s", result.stderr)
                return False
            lines = [line for line in result.stdout.splitlines()[1:] if line.strip()]
            return any("\tdevice" in line for line in lines)
        except Exception as e:
            logger.warning("Could not run 'adb devices': %s", e)
            return False

    def _adb_wait_for_device(timeout_seconds: int) -> None:
        try:
            subprocess.run(["adb", "wait-for-device"], timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            logger.warning("'adb wait-for-device' timed out after %ss", timeout_seconds)
        except Exception as e:
            logger.warning("'adb wait-for-device' failed: %s", e)

    for attempt_index in range(1, max_retries + 1):
        logger.info("Connecting to device (attempt %s/%s)…", attempt_index, max_retries)

        if not _adb_has_devices():
            logger.error(
                "No ADB devices detected. Is a device/emulator connected and authorized?"
            )
            if attempt_index < max_retries:
                _adb_wait_for_device(retry_delay)
                continue
            _fatal(None, "No devices detected by ADB after all attempts")

        try:
            device = u2.connect()
            # Touch the device to ensure the connection is usable
            _ = device.device_info  # may raise if not connected
            logger.info("Connected to device.")

            # Configure device defaults for stability
            try:
                device.settings["compressHierarchy"] = False
            except Exception:
                pass

            # Set a implicit wait to reduce flakiness
            try:
                device.implicitly_wait(5.0)
            except Exception:
                pass

            # run healthcheck() to avoid RPC errors
            try:
                device.healthcheck()
            except Exception:
                pass

            # Warm up the accessibility service / hierarchy
            ready = False
            try:
                ready = _warmup_accessibility_and_hierarchy(
                    device, timeout=12.0, interval=0.5
                )
            except Exception as e:
                logger.debug("Warm-up helper raised: %s", e)
            if not ready:
                logger.warning(
                    "Accessibility not confirmed ready; proceeding cautiously"
                )

            return device

        except Exception as e:
            logger.info("Connection failed: %s", e)
            if attempt_index < max_retries:
                _adb_wait_for_device(retry_delay)
                continue
            _fatal(
                None, f"Failed to connect to device after {max_retries} attempts: {e}"
            )


# =============================================================================
# PUBLIC UI ELEMENT INTERACTION FUNCTIONS
# =============================================================================


def wait_and_click(d, element, timeout=180, exit_on_error=True):
    """Wait for an element and click it with ANR awareness and no sleeps."""
    if not _wait_for_element(
        d, element, timeout=timeout
    ):  # Element not found; raise error/fatal if
        message = f"Could not find element: '{element.selector}' within {timeout}s"
        if exit_on_error:
            _fatal(d, message)
        else:
            logger.error("%s", message)
            return False

    if not element.click_exists(timeout=5):
        message = f"Could not click element: '{element.selector}'"
        if exit_on_error:
            _fatal(d, message)
        else:
            logger.error("%s", message)
            return False

    # Clicked element; return True
    logger.info("Clicked element %s", element.selector)

    return True


def wait_and_set_text(d, element, text, timeout=180, exit_on_error=True):
    """Wait for an input element, focus it, set text, then handle IME action."""
    if not _wait_for_element(d, element, timeout=timeout):
        message = f"Could not find element: '{element.selector}' within {timeout}s"
        if exit_on_error:
            _fatal(d, message)
        else:
            logger.error("%s", message)
            return False

    # Use robust text entry with retries and scroll support
    try:
        # Focus the element before setting text to mirror click flow semantics
        element.click_exists(timeout=5)
        _robust_set_text(d, element, text, max_attempts=3)
    except Exception as e:
        message = f"Failed to set text on element: '{element.selector}': {e}"
        if exit_on_error:
            _fatal(d, message)
        else:
            logger.error("%s", message)
            return False

    logger.info("Set text to %s", text)
    _handle_keyboard_action(d)

    return True


def wait_for_ui_stable(d, timeout=5, interval=0.5, min_consecutive=3):
    prev_hierarchy = None
    same_count = 0
    start = time.time()

    while time.time() - start < timeout:
        try:
            current_hierarchy = d.dump_hierarchy()
        except Exception as e:
            logger.debug("Failed to dump UI hierarchy during stability check: %s", e)
            time.sleep(interval)
            continue

        # Count consecutive identical dumps
        if prev_hierarchy is not None and current_hierarchy == prev_hierarchy:
            same_count += 1
        else:
            same_count = 1

        prev_hierarchy = current_hierarchy

        # Return True if the UI has stabilized for at least min_consecutive samples
        if same_count >= min_consecutive:
            logger.debug("UI stabilized in %.1fs", time.time() - start)
            return True

        # Wait for some time to avoid false positive before screen transitions
        time.sleep(interval)

    logger.warning(
        "UI did not stabilize within %.1fs (required %s consecutive identical dumps).",
        time.time() - start,
        min_consecutive,
    )
    return False


# =============================================================================
# PRIVATE STABILITY HELPERS
# =============================================================================


def _warmup_accessibility_and_hierarchy(d, timeout=8.0, interval=0.5):
    """
    Ensure UiAutomator's accessibility service is bound before we rely on hierarchy.
    Returns True if hierarchy dump works; False if we give up.
    """
    deadline = time.time() + timeout
    # Make sure we don't trigger compressed-dump path on flaky ROMs
    try:
        d.settings["compressHierarchy"] = False
    except Exception:
        pass

    while time.time() < deadline:
        try:
            # A successful dump means the service is up
            _ = d.dump_hierarchy()
            logger.debug("Accessibility/hierarchy warm-up succeeded.")
            return True
        except Exception as e:
            msg = str(e)
            # Classic race signature from your stacktrace:
            # "AccessibilityServiceInfo.flags on a null object"
            if "AccessibilityServiceInfo.flags" in msg or "NullPointerException" in msg:
                logger.debug("Hierarchy dump failed (race condition). Retrying…")
            else:
                # Other failures should still retry briefly, but log at debug.
                logger.debug("Hierarchy dump error during warm-up: %s", e)
            time.sleep(interval)


def _wait_for_element(d, element, timeout=180):
    """
    Wait for an element to exist while continuously handling potential ANR dialogs.

    Args:
        d: Device object
        element: UI element to wait for
        timeout: Maximum time to wait in seconds

    Returns:
        True if the element exists on UI hierarchy within the timeout, False otherwise
    """
    start_time = time.time()

    selector_info = _parse_selector_from_element(element)

    if not element.exists:
        _try_scroll_into_view(d, selector_info)

    while time.time() - start_time < timeout:
        if not _handle_anr(
            d, max_anrs=5, timeout=1, target_element=element
        ):  # Failed to unfreeze system UI; abort early
            return False

        remaining = max(0, timeout - (time.time() - start_time))
        wait_slice = min(1, remaining)
        try:
            if element.wait(timeout=wait_slice):  # Element found; return True
                return True
        except Exception:
            # If wait is not available for some reason, fall back to existence check
            if element.exists:
                return True

        _try_scroll_into_view(d, selector_info)

    return False


def _handle_anr(d, max_anrs=5, timeout=3, target_element=None):
    """Click ANR 'Wait' up to max_anrs times; settle with idle/stable checks."""
    anr_count = 0
    wait_button = d(resourceId="android:id/aerr_wait")

    for _ in range(max_anrs):
        try:
            if wait_button.exists(timeout=timeout):
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
                    if target_element.wait(timeout=5):
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
                    wait_for_ui_stable(d, timeout=5)
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


def _fatal(d, message):
    logger.critical("%s", message)
    try:
        if d is not None:
            try:
                logger.critical("%s", d.dump_hierarchy())
            except Exception as dump_err:
                # Ignore the classic accessibility bind race to avoid masking the real error
                if "AccessibilityServiceInfo.flags" in str(
                    dump_err
                ) or "NullPointerException" in str(dump_err):
                    logger.warning(
                        "Skipped hierarchy dump (accessibility not ready): %s", dump_err
                    )
                else:
                    logger.warning("Failed to dump UI hierarchy: %s", dump_err)
    except Exception as outer:
        logger.warning("Fatal handler encountered an error: %s", outer)
    sys.exit(1)


# =============================================================================
# PRIVATE TEXT ENTRY HELPERS (robust set_text with retries/scroll + end keyboard action)
# =============================================================================


def _handle_keyboard_action(d):
    """Trigger IME action via Done button, IME action key, or Enter key."""
    # Handle any ANRs before keyboard interaction
    _handle_anr(d, max_anrs=5, timeout=1, target_element=None)

    # Method 1: Try clicking the keyboard Done button
    try:
        if d(description="Done").exists(timeout=1):
            d(description="Done").click()
            logger.debug("Clicked keyboard Done button")
            return True
    except Exception as e:
        logger.warning("Could not click keyboard Done button: %s", e)

    # Method 2: Try clicking the keyboard action button
    try:
        if d(
            resourceId="com.google.android.inputmethod.latin:id/key_pos_ime_action"
        ).exists(timeout=1):
            d(
                resourceId="com.google.android.inputmethod.latin:id/key_pos_ime_action"
            ).click()
            logger.debug("Clicked keyboard action button")
            return True
    except Exception as e:
        logger.warning("Could not click keyboard action button: %s", e)

    # Method 3: Try pressing Enter key
    try:
        d.press("enter")
        logger.debug("Pressed Enter key")
        return True
    except Exception as e:
        logger.warning("Could not press Enter key: %s", e)

    logger.error("All keyboard action methods failed")
    return False


def _parse_selector_from_element(element):
    """
    Extract selector attributes from a uiautomator2 element for downstream use.
        - This helper parses the string form of the selector and returns a
          dictionary so that `_try_scroll_into_view` can do:
              scroll.to(resourceId=...) or scroll.to(text=...)

    Example:
        Input string:  "Selector [resourceId='LoginPasswordEntry']"
        Output dict:   {"resourceId": "LoginPasswordEntry"}

    Notes:
        - Falls back to an empty dict if the selector cannot be parsed.
        - Safe to call on any element; non-fatal on parsing errors.
    """
    try:
        selector_string = str(element.selector)
        # Extract inside the brackets
        bracket_match = re.search(r"\[(.*)\]", selector_string)
        if not bracket_match:
            return {}
        inside = bracket_match.group(1)
        pairs = re.findall(r"(\w+)='([^']+)'", inside)
        return {key: value for key, value in pairs}
    except Exception:
        return {}


def _try_scroll_into_view(d, selector_info):
    """
    Attempts to scroll the screen so that an element becomes visible, using selector info.
    Prefers resourceId, falls back to text if available.
    Returns True if a scroll attempt was made, False otherwise.
    """
    try:
        scrollable = d(scrollable=True)
        if not scrollable.exists:
            return False

        if "resourceId" in selector_info:
            scrollable.scroll.to(resourceId=selector_info["resourceId"])
            return True
        if "text" in selector_info:
            scrollable.scroll.to(text=selector_info["text"])
            return True
        return False
    except Exception:
        return False


def _robust_set_text(d, element, text, max_attempts=3):
    """
    Tries to set text into an element with retries, ANR handling, and optional scrolling.
    Returns True on success; raises fatal error after exhausting retries.
    """
    selector_info = _parse_selector_from_element(element)

    for attempt_index in range(1, max_attempts + 1):
        # Handle any ANR dialogs and wait for the target element
        _handle_anr(d, max_anrs=5, timeout=1, target_element=element)

        try:
            # Bring element into view and focus it
            if not element.exists:
                _try_scroll_into_view(d, selector_info)

            element.click_exists(timeout=5)
            element.set_text(text)
            logger.debug(
                "Set text attempt %s succeeded for %s", attempt_index, element.selector
            )
            return True
        except Exception as set_error:
            logger.warning("set_text attempt %s failed: %s", attempt_index, set_error)
            wait_for_ui_stable(d, timeout=1.5, interval=0.3, min_consecutive=2)

    raise RuntimeError(
        f"Exhausted {max_attempts} attempts to set text on element: '{element.selector}'"
    )
