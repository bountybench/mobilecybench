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
from pathlib import Path

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


def _preflight_emulator_readiness():
    """Run the android emulator readiness script once with configurable timeouts."""
    try:
        project_root = Path(__file__).resolve().parents[1]
        script_path = project_root / "utils" / "android_emulator_ready.sh"
        if not script_path.exists():
            logger.debug(
                "Readiness script not found at %s; skipping preflight.", script_path
            )
            return

        logger.info("Running emulator readiness preflight: %s", script_path)
        subprocess.run([str(script_path)], check=True)
    except subprocess.CalledProcessError as e:
        logger.error("Readiness preflight failed with exit code %s", e.returncode)
        raise
    except Exception as e:
        logger.debug("Preflight readiness skipped: %s", e)
        return


def initialize_ui_automation(max_retries=5, retry_delay=15):
    """Connect to a device and enable sane defaults (implicit waits, no sleeps)."""

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
            _preflight_emulator_readiness()
        except Exception as e:
            logger.warning(
                "Readiness preflight script failed: %s. Continuing with Python checks…",
                e,
            )

        try:
            logger.debug("Attempting to connect uiautomator2 client...")
            device = u2.connect()
            logger.info("Connected to device.")

            # Configure device defaults for stability
            logger.debug("Configuring device settings...")
            try:
                device.settings["compressHierarchy"] = False
            except Exception:
                pass

            # run healthcheck() to avoid RPC errors
            logger.debug("Running health check...")
            try:
                device.healthcheck()
            except Exception:
                pass

            logger.debug("UI automation client is ready.")
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

    if not _wait_for_element(d, element, timeout=timeout):
        app_state = d.app_current()
        message = (
            f"Could not find element: '{element.selector}' within {timeout}s.\n"
            f"  - Current screen: {app_state.get('package', 'unknown')}/{app_state.get('activity', 'unknown')}."
        )
        if exit_on_error:
            _fatal(d, message)
        else:
            logger.error("%s", message)
            return False
    else:
        logger.debug("Found element %s", element.selector)

    # Prefer robust built-in wait-and-click first
    try:
        if element.click_exists(timeout=10):
            logger.info("Clicked element %s", element.selector)
            return True
    except Exception as e:
        logger.debug("click_exists failed fast for %s: %s", element.selector, e)

    # Fallback: poll for clickability and click once ready
    try:
        start_time = time.time()
        wait_clickable_timeout = 10
        while time.time() - start_time < wait_clickable_timeout:
            try:
                info = element.info
            except Exception as info_err:
                logger.debug(
                    "Failed to read element.info while waiting clickable: %s", info_err
                )
                time.sleep(0.5)
                continue

            if info.get("clickable"):
                try:
                    element.click()
                    logger.info("Clicked element %s", element.selector)
                    return True
                except Exception as click_err:
                    logger.debug(
                        "Direct click failed after clickable=true: %s", click_err
                    )
            time.sleep(0.5)

        # 4) Last attempt: best-effort direct click
        element.click()
        logger.info("Clicked element %s (best-effort)", element.selector)
        return True

    except Exception as e:
        # Build diagnostic context safely
        try:
            elem_info = element.info
            clickable = elem_info.get("clickable")
            enabled = elem_info.get("enabled")
            visible_bounds = elem_info.get("visibleBounds")
        except Exception:
            clickable = enabled = visible_bounds = "<unavailable>"

        message = (
            f"Found element '{element.selector}' but it could not be clicked: {e}\n"
            f"  - Clickable: {clickable}, Enabled: {enabled}\n"
            f"  - Visible Bounds: {visible_bounds}"
        )
        if exit_on_error:
            _fatal(d, message)
        else:
            logger.error("%s", message)
            return False


def wait_and_set_text(d, element, text, timeout=180, exit_on_error=True):
    """Focus the input by clicking it, set text, then finalize IME action."""

    # Reuse the robust click flow to focus the field first
    clicked = wait_and_click(d, element, timeout=timeout, exit_on_error=exit_on_error)
    if not clicked:
        return False

    try:
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

    wait_for_ui_stable(d)

    return True


def wait_for_ui_stable(d, timeout=10, interval=0.5, min_consecutive=3):
    prev_dump = None
    same_count = 0
    start = time.time()
    fail_count = 0

    while time.time() - start < timeout:
        try:
            current_dump = d.dump_hierarchy()
            fail_count = 0
        except Exception as e:
            # This specific NullPointerException is a known race condition during screen transitions.
            # We treat it as a signal that the UI is in flux, not a hard error.
            if "java.lang.NullPointerException" in str(
                e
            ) and "AccessibilityServiceInfo.flags" in str(e):
                logger.debug(
                    "Caught accessibility service race condition, waiting for UI to settle..."
                )
                time.sleep(1)  # Give a longer pause for the service to recover
                fail_count += 1
            else:
                logger.debug(
                    "Failed to get hierarchy dump during stability check: %s", e
                )
                fail_count += 1

            if fail_count >= 3:
                try:
                    logger.debug(
                        "Running health check after %d consecutive failures...",
                        fail_count,
                    )
                    d.healthcheck()
                except Exception as health_err:
                    logger.warning("Health check also failed: %s", health_err)
            time.sleep(interval)
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
        time.sleep(interval)

    logger.warning(
        "UI did not stabilize (hierarchy dump) within %.1fs (required %s consecutive identical samples).",
        time.time() - start,
        min_consecutive,
    )
    return False


# =============================================================================
# PRIVATE ADB INITIALIZATION HELPERS
# =============================================================================


def _adb_has_devices(timeout_seconds=5):
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


def _adb_wait_for_device(timeout_seconds):
    try:
        subprocess.run(["adb", "wait-for-device"], timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        logger.warning("'adb wait-for-device' timed out after %ss", timeout_seconds)
    except Exception as e:
        logger.warning("'adb wait-for-device' failed: %s", e)


def _handle_transition(d, old_activity, timeout=3):
    """Waits for a short period to see if an activity transition occurs."""
    logger.debug("Checking for screen transition from '%s'...", old_activity)
    start = time.time()
    while time.time() - start < timeout:
        try:
            current_activity = d.app_current().get("activity")
            if current_activity and current_activity != old_activity:
                logger.debug(
                    "Screen transition detected: '%s' -> '%s' in %.1fs",
                    old_activity,
                    current_activity,
                    time.time() - start,
                )
                # Now that we've detected a transition, wait briefly for it to settle before the more intense
                # hierarchy check in wait_for_ui_stable begins.
                time.sleep(1)
                return
        except Exception:
            # Errors are expected here if the UI is in a deep state of flux.
            pass
        time.sleep(0.5)
    logger.debug("No screen transition detected within %ss.", timeout)


# =============================================================================
# PRIVATE UI UTILITY HELPERS
# =============================================================================


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

    try:
        selector_str = str(getattr(element, "selector", element))
    except Exception:
        selector_str = "<unknown>"
    logger.debug("Waiting for element %s (timeout=%ss)", selector_str, timeout)

    selector_info = _parse_selector_from_element(element)

    while time.time() - start_time < timeout:
        try:
            app_state = d.app_current()
            current_pkg = app_state.get("package", "")
            current_activity = app_state.get("activity", "")
            target_pkg = os.getenv("UI_TARGET_PACKAGE")
            if target_pkg and current_pkg and current_pkg != target_pkg:
                logger.error(
                    "Not on target app (current=%s/%s, target=%s).",
                    current_pkg,
                    current_activity,
                    target_pkg,
                )
                return False
        except Exception as e:
            logger.debug("Could not inspect current app state: %s", e)

        if not _handle_anr(
            d, max_anrs=5, timeout=1, target_element=element
        ):  # Failed to unfreeze system UI; abort early
            return False

        remaining = max(0, timeout - (time.time() - start_time))
        wait_slice = min(1, remaining)
        try:
            if element.wait(timeout=wait_slice):  # Element found; return True
                logger.debug(
                    "Element %s appeared after %.1fs",
                    selector_str,
                    time.time() - start_time,
                )
                return True
            else:
                logger.debug(
                    "Element %s did not appear after %.1fs",
                    selector_str,
                    time.time() - start_time,
                )
        except Exception:
            # If wait is not available for some reason, fall back to existence check
            if element.exists:
                logger.debug("Element %s already exists (no wait).", selector_str)
                return True

        try:
            did_scroll = _try_scroll_into_view(d, selector_info)
            if did_scroll:
                logger.debug(
                    "Attempted scroll into view using selector info: %s", selector_info
                )
        except Exception as e:
            logger.debug("Error during scroll attempt: %s", e)

        time.sleep(0.5)

    logger.debug(
        "Timed out after %.1fs waiting for element %s",
        time.time() - start_time,
        selector_str,
    )
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


def _robust_set_text(d, element, text, max_attempts=3, retry_delay=1.0):
    """
    Set text with verification and retries. Assumes caller has already focused the field.
    Strategy:
      1) Try set_text directly; verify via get_text
      2) On failure, click then set_text; verify
      3) On failure, click + clear_text + set_text; verify
      4) Retry up to max_attempts with small delay; handle ANRs between attempts
    """
    last_err = None
    for attempt_index in range(1, max_attempts + 1):
        try:
            _handle_anr(d, max_anrs=5, timeout=1, target_element=element)

            # First attempt: set_text directly
            try:
                element.set_text(text)
            except Exception:
                # Focus, then retry set_text
                try:
                    element.click()
                except Exception:
                    pass
                element.set_text(text)

            time.sleep(0.5)
            try:
                current = element.get_text()
            except Exception:
                current = None
            if current == text:
                logger.debug("Set text verified on attempt %s.", attempt_index)
                return True

            # Retry path: click + clear + set + verify
            try:
                element.click()
            except Exception:
                pass
            try:
                element.clear_text()
            except Exception:
                pass
            element.set_text(text)

            time.sleep(0.5)
            try:
                current = element.get_text()
            except Exception:
                current = None
            if current == text:
                logger.debug(
                    "Set text verified after clear on attempt %s.", attempt_index
                )
                return True

            last_err = RuntimeError(
                f"Verification failed. Expected: '{text}', Got: '{current}'"
            )
        except Exception as e:
            last_err = e

        if attempt_index < max_attempts:
            time.sleep(retry_delay)

    raise (
        last_err
        if last_err
        else RuntimeError(f"Failed to set text on element: '{element.selector}'")
    )


# =============================================================================
# PRIVATE FATAL ERROR HANDLER
# =============================================================================


def _fatal(d, message):
    """
    Fatal error handler that logs the error message, raw adb logs, and UI hierarchy.
    """
    logger.critical("%s", message)

    # Output raw adb logs
    try:
        result = subprocess.run(
            ["adb", "logcat", "-d", "-t", "500"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        logger.critical("Raw adb logcat output:\n%s", result.stdout)
    except Exception as e:
        logger.warning("Failed to get adb logcat output: %s", e)

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
