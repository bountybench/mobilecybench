"""
uiautomator2 helpers for reliable clicking and text entry.
Public API: initialize_ui_automation, wait_and_click, wait_and_set_text, wait_for_ui_stable
"""

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import uiautomator2 as u2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ANDROID_READY_SCRIPT = PROJECT_ROOT / "utils" / "android_emulator_ready.sh"

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


def initialize_ui_automation(max_retries=5, retry_delay=15):
    """Connect to a device with uiautomator2"""

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

            logger.debug("Configuring device settings...")
            _configure_device_defaults(device)

            logger.debug("UI automation client is ready.")
            return device

        except Exception as e:
            logger.info("Connection failed: %s", e)
            if attempt_index < max_retries:
                time.sleep(retry_delay)
                continue
            _fatal(
                None, f"Failed to connect to device after {max_retries} attempts: {e}"
            )


# =============================================================================
# PUBLIC UI ELEMENT INTERACTION FUNCTIONS
# =============================================================================


def wait_and_click(d, element, timeout=180):
    """Wait for an element and click it with ANR awareness and no sleeps."""

    if not _wait_for_element(d, element, timeout=timeout):
        app_state = d.app_current() or {}
        current_pkg = app_state.get("package", "unknown")
        current_activity = app_state.get("activity", "unknown")
        message = (
            f"Could not find element: '{element.selector}' within {timeout}s.\n"
            f"  - Current screen: {current_pkg}/{current_activity}."
        )
        _fatal(d, message)
    else:
        logger.debug("Found element %s", element.selector)

    try:
        if element.click_exists(timeout=10):
            logger.info("Clicked element %s", element.selector)
            return True
    except Exception as e:
        logger.debug("click_exists failed for %s: %s", element.selector, e)
        try:
            elem_info = element.info
            clickable = elem_info.get("clickable")
            enabled = elem_info.get("enabled")
        except Exception:
            clickable = enabled = "<unavailable>"

        message = (
            f"Found element '{element.selector}' but it could not be clicked: {e}\n"
            f"  - Clickable: {clickable}, Enabled: {enabled}"
        )
        _fatal(d, message)


def wait_and_set_text(d, element, text, max_attempts=3, retry_delay=1.0, timeout=180):
    """Focus the input by clicking it, set text, then finalize IME action."""

    # Use the robust click flow to focus the field first
    clicked = wait_and_click(d, element, timeout=timeout)
    if not clicked:
        return False

    for attempt_index in range(1, max_attempts + 1):
        try:
            element.set_text(text)
            logger.debug("Set text on attempt %s.", attempt_index)
            logger.info("Set text to %s", text)

            # Prefer IME-agnostic finalize: send Enter, then fallback
            try:
                d.send_keys("\n")
            except Exception:
                try:
                    d.press("enter")
                except Exception:
                    _handle_keyboard_action(d)

            wait_for_ui_stable(d)
            return True

        except Exception as e:
            logger.debug("Set text failed on attempt %s: %s", attempt_index, e)
            if attempt_index < max_attempts:
                time.sleep(retry_delay)
            else:
                message = f"Failed to set text on element: '{element.selector}' after {max_attempts} attempts"
                _fatal(d, message)


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
            app_state = d.app_current() or {}
            current_pkg = app_state.get("package") or ""
            current_activity = app_state.get("activity") or ""
            # If launcher is in foreground, the requested element cannot appear
            if _is_launcher_activity(current_pkg, current_activity):
                logger.debug(
                    "Launcher detected in foreground (%s/%s); aborting element wait. UI cannot become stable.",
                    current_pkg,
                    current_activity,
                )
                return False
            # Known UiAutomator races during transitions; treat as transient
            if "java.lang.NullPointerException" in str(
                e
            ) and "AccessibilityServiceInfo.flags" in str(e):
                logger.debug(
                    "Caught accessibility service race condition, waiting for UI to settle..."
                )
                time.sleep(1)
                fail_count += 1
            else:
                logger.debug(
                    "Failed to get hierarchy dump during stability check: %s", e
                )
                fail_count += 1

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


def _configure_device_defaults(device):
    """Apply safe, fast defaults on a connected device (best-effort)."""
    try:
        device.settings["compressHierarchy"] = False
    except Exception:
        pass
    try:
        device.set_fastinput_ime(True)
    except Exception:
        pass
    try:
        device.wait_idle(timeout=2)
    except Exception:
        pass
    try:
        device.healthcheck()
    except Exception:
        pass


# =============================================================================
# PRIVATE UI UTILITY HELPERS
# =============================================================================


def _is_launcher_activity(current_pkg: str, current_activity: str) -> bool:
    """
    Heuristically determine if the current foreground activity is a launcher.

    Uses common launcher package names and a substring match on activity/package.
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


def _wait_for_element(d, element, timeout=180):
    """
    Wait for an element to exist while continuously handling potential ANR dialogs.
    """
    start_time = time.time()

    # Derive selector string and parse attributes separately
    try:
        selector_str = str(getattr(element, "selector", element))
    except Exception:
        selector_str = "<unknown>"
    selector_info = _parse_selector_from_element(element)

    logger.debug("Waiting for element %s (timeout=%ss)", selector_str, timeout)

    while time.time() - start_time < timeout:
        try:
            # app_current() may return None transiently; guard with fallback
            app_state = d.app_current() or {}
            current_pkg = app_state.get("package") or ""
            current_activity = app_state.get("activity") or ""
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

        # Try to scroll element into view using parsed selector attributes
        try:
            if selector_info:
                scrollable = d(scrollable=True)
                if scrollable.exists:
                    if "resourceId" in selector_info:
                        scrollable.scroll.to(resourceId=selector_info["resourceId"])
                        logger.debug(
                            "Scrolled to element using resourceId: %s",
                            selector_info["resourceId"],
                        )
                    elif "text" in selector_info:
                        scrollable.scroll.to(text=selector_info["text"])
                        logger.debug(
                            "Scrolled to element using text: %s", selector_info["text"]
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
    """
    Trigger IME action via Done button, IME action key, or Enter key.
    Various Android SDKs use various keyboard action buttons.
    """
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
    Extract selector attributes from a uiautomator2 element.

    Returns:
        dict: Parsed attributes (e.g., resourceId, text). Never None.
    """

    attributes = {}

    try:
        # Check if element has direct access to selector attributes
        if hasattr(element, "resourceId") and getattr(element, "resourceId"):
            attributes["resourceId"] = element.resourceId
        if hasattr(element, "text") and getattr(element, "text"):
            attributes["text"] = element.text
        if attributes:
            logger.debug(
                "Selector parsed using direct access: %s", list(attributes.keys())
            )
            logger.debug("Selector attributes: %s", attributes)
            return attributes
    except Exception:
        logger.debug("Selector parsing failed")
        return attributes


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
            ["adb", "logcat", "-t", "200"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.stdout:
            logger.critical("Raw adb logcat output:\n%s", result.stdout)
        if result.stderr:
            logger.critical("Raw adb logcat stderr:\n%s", result.stderr)
    except Exception as e:
        logger.warning("Failed to get adb logcat output: %s", e)

    try:
        if d is not None:
            try:
                logger.critical("%s", d.dump_hierarchy())
            except Exception as dump_err:
                # Ignore the classic accessibility bind race to avoid masking the real error
                if "NullPointerException" in str(dump_err):
                    logger.warning(
                        "Skipped hierarchy dump (NullPointerException): %s", dump_err
                    )
                else:
                    logger.warning("Failed to dump UI hierarchy: %s", dump_err)
    except Exception as outer:
        logger.warning("Fatal handler encountered an error: %s", outer)

    sys.exit(1)
