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
UI_MAX_RETRIES = 5
UI_RETRY_DELAY = 15
UI_MAX_SCROLLS = 8

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


def initialize_ui_automation():
    """Connect to a device with uiautomator2"""

    try:
        _preflight_emulator_readiness()
    except Exception as e:
        logger.warning("Readiness preflight script failed: %s.", e)

    for attempt_index in range(1, UI_MAX_RETRIES + 1):
        logger.info(
            "Connecting to device (attempt %s/%s)…", attempt_index, UI_MAX_RETRIES
        )

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
            if attempt_index < UI_MAX_RETRIES:
                time.sleep(UI_RETRY_DELAY)
                continue
            _fatal(
                None,
                f"Failed to connect to device after {UI_MAX_RETRIES} attempts: {e}",
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
            _ensure_target_app_foreground(d)
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
            # Ensure the correct app is in foreground before typing
            _ensure_target_app_foreground(d)

            # Re-ensure the element is present and focused before typing
            if not element.exists:
                _wait_for_element(d, element, timeout=5)
            try:
                # In case focus was lost, try to click again quickly
                element.click_exists(timeout=2)
            except Exception:
                pass

            element.set_text(text)

            logger.debug("Set text on attempt %s.", attempt_index)
            logger.info("Set text to %s", text)

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
        # Set fastinput IME to True to avoid various IME handling logic
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


def _is_launcher_activity(current_pkg, current_activity):
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


def _ensure_target_app_foreground(d, wait_timeout=10.0, stabilize_timeout=5.0):
    """
    Ensure the target app (from UI_TARGET_PACKAGE) is in the foreground.
    If the launcher or a different app is foreground, attempt to bring the target app
    to front. Best-effort; returns True if foreground looks correct after attempts.
    """
    try:
        app_state = d.app_current() or {}
        current_pkg = app_state.get("package") or ""
        current_activity = app_state.get("activity") or ""

        target_pkg = os.getenv("UI_TARGET_PACKAGE") or ""
        if not target_pkg:
            # Nothing to enforce
            return True

        # If launcher is shown or we're on a different app, try to recover
        if _is_launcher_activity(current_pkg, current_activity) or (
            current_pkg and current_pkg != target_pkg
        ):
            try:
                logger.debug(
                    "Foreground is %s/%s; attempting to bring %s to front...",
                    current_pkg,
                    current_activity,
                    target_pkg,
                )
                d.app_start(target_pkg, wait=True, stop=False)
                d.app_wait(target_pkg, front=True, timeout=wait_timeout)
                if stabilize_timeout and stabilize_timeout > 0:
                    wait_for_ui_stable(d, timeout=stabilize_timeout)
            except Exception as relaunch_err:
                logger.debug("Could not ensure target app foreground: %s", relaunch_err)

        return True
    except Exception:
        return False


def _wait_for_element(d, element, timeout=180):
    """Wait for an element; if missing, perform limited coarse scrolls to reveal it."""
    start = time.time()
    try:
        selector_str = str(getattr(element, "selector", element))
    except Exception:
        selector_str = "<unknown>"

    coarse_scrolls = 0
    while time.time() - start < timeout:
        try:
            # app_current() may return None transiently; guard with fallback
            app_state = d.app_current() or {}
            current_pkg = app_state.get("package") or ""
            current_activity = app_state.get("activity") or ""
            target_pkg = os.getenv("UI_TARGET_PACKAGE")
            if target_pkg and current_pkg and current_pkg != target_pkg:
                logger.debug(
                    "Not on target app yet (current=%s/%s, target=%s). Continuing to wait.",
                    current_pkg,
                    current_activity,
                    target_pkg,
                )
        except Exception as e:
            logger.debug("Could not inspect current app state: %s", e)

        if not _handle_anr(
            d, max_anrs=5, timeout=1, target_element=element
        ):  # Failed to unfreeze system UI; abort early
            return False

        # Short wait slice; return early when found
        if element.wait(timeout=0.75) or element.exists:
            return True

        # Coarse scroll forward to try to reveal the element
        try:
            scroller = d(scrollable=True)
            if scroller.exists and coarse_scrolls < UI_MAX_SCROLLS:
                coarse_scrolls += 1
                try:
                    scroller.scroll.forward(steps=20)
                except Exception:
                    pass
        except Exception:
            pass

        time.sleep(0.25)

    logger.debug("Timed out waiting for %s", selector_str)
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
# PRIVATE FATAL ERROR HANDLER
# =============================================================================


def _fatal(d, message):
    """
    Fatal error handler that logs the error message, raw adb logs, and UI hierarchy.
    """
    logger.critical("%s", message)

    logger.debug("Current pacakge: %s", d.app_current().get("package"))
    logger.debug("Current activity: %s", d.app_current().get("activity"))

    # Output raw adb logs
    try:
        subprocess.run(["adb", "logcat", "-t", "200"], stdout=sys.stderr, timeout=10)
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
