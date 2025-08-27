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


def initialize_ui_automation(max_retries=5, retry_delay=15):
    """Connect to a device and enable sane defaults (implicit waits, no sleeps)."""

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

    def _wait_for_system_services(timeout=90):
        """
        Actively probes core Android services to ensure the emulator is stable
        before attempting to connect the UI automation client. This prevents a
        common race condition that can lead to a DeadSystemException.
        """
        logger.info("Probing core system services for stability...")
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # Check 1: system_server process must be running.
                pid_check = subprocess.run(
                    ["adb", "shell", "pidof", "system_server"],
                    capture_output=True,
                    timeout=5,
                )
                if pid_check.returncode != 0:
                    time.sleep(2)
                    continue

                # Check 2: PackageManager must be responsive.
                pm_check = subprocess.run(
                    ["adb", "shell", "pm", "list", "packages"],
                    capture_output=True,
                    timeout=5,
                )
                if pm_check.returncode != 0:
                    time.sleep(2)
                    continue

                # Check 3: ActivityManager must be responsive.
                am_check = subprocess.run(
                    ["adb", "shell", "service", "check", "activity"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if am_check.returncode != 0 or "found" not in am_check.stdout:
                    time.sleep(2)
                    continue

                logger.info("Core system services are stable.")
                return True
            except Exception:
                time.sleep(2)
        logger.warning("Core system services did not stabilize within %ss.", timeout)
        return False

    # Log auto-relaunch linkage once for visibility
    try:
        target_pkg_env = os.getenv("UI_TARGET_PACKAGE", "")
        if target_pkg_env:
            logger.info("UI auto-relaunch target package: %s", target_pkg_env)
        else:
            logger.info("UI auto-relaunch target package: (not set)")
    except Exception:
        pass

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

        # Actively probe core services before connecting.
        if not _wait_for_system_services():
            logger.error(
                "Emulator detected, but its core services are not stable. Retrying..."
            )
            if attempt_index < max_retries:
                _adb_wait_for_device(retry_delay)
                continue
            _fatal(None, "Emulator core services did not stabilize after all attempts.")

        try:
            device = u2.connect()
            logger.info("Connected to device.")

            # Configure device defaults for stability
            try:
                device.settings["compressHierarchy"] = False
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
                    device, timeout=30.0, interval=1.0
                )
            except Exception as e:
                logger.debug("Warm-up helper raised: %s", e)
            if not ready:
                _fatal(
                    device,
                    "UiAutomator/Accessibility service not ready after all attempts.",
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
        app_state = d.app_current()
        message = (
            f"Could not find element: '{element.selector}' within {timeout}s.\n"
            f"  - Current screen: {app_state.get('package', 'unknown')}/{app_state.get('activity', 'unknown')}.\n"
            f"  - See the full UI hierarchy dump below for details."
        )
        if exit_on_error:
            _fatal(d, message)
        else:
            logger.error("%s", message)
            return False
    else:
        logger.debug("Found element %s", element.selector)

    if not element.click_exists(timeout=5):
        app_state = d.app_current()
        elem_info = element.info
        message = (
            f"Found element '{element.selector}' but it could not be clicked.\n"
            f"  - Is it visible? {elem_info.get('visibleBounds')}\n"
            f"  - Is it clickable? {elem_info.get('clickable')}\n"
            f"  - Is it enabled? {elem_info.get('enabled')}\n"
            f"  - Current screen: {app_state.get('package', 'unknown')}/{app_state.get('activity', 'unknown')}.\n"
            f"  - See the full UI hierarchy dump below for details."
        )
        if exit_on_error:
            _fatal(d, message)
        else:
            logger.error("%s", message)
            return False

    # Clicked element; return True
    logger.info("Clicked element %s", element.selector)

    wait_for_ui_stable(d)

    return True


def wait_and_set_text(d, element, text, timeout=180, exit_on_error=True):
    """Wait for an input element, focus it, set text, then handle IME action."""
    if not _wait_for_element(d, element, timeout=timeout):
        app_state = d.app_current()
        message = (
            f"Could not find element: '{element.selector}' within {timeout}s.\n"
            f"  - Current screen: {app_state.get('package', 'unknown')}/{app_state.get('activity', 'unknown')}.\n"
            f"  - See the full UI hierarchy dump below for details."
        )
        if exit_on_error:
            _fatal(d, message)
        else:
            logger.error("%s", message)
            return False
    else:
        logger.debug("Found element %s", element.selector)

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

    wait_for_ui_stable(d)

    return True


def wait_for_ui_stable(d, timeout=10, interval=0.5, min_consecutive=3):
    prev_dump = None
    same_count = 0
    start = time.time()
    fail_count = 0
    npe_seq_count = 0  # Track consecutive accessibility NPEs so we can heal

    while time.time() - start < timeout:
        try:
            current_dump = d.dump_hierarchy()
            fail_count = 0
            npe_seq_count = 0
        except Exception as e:
            logger.debug("Failed to get hierarchy dump during stability check: %s", e)
            fail_count += 1
            if fail_count == 3:
                try:
                    d.healthcheck()
                except Exception:
                    pass
            # Self-heal when we observe the classic AccessibilityService NPE repeatedly
            try:
                if "AccessibilityServiceInfo.flags" in str(
                    e
                ) or "NullPointerException" in str(e):
                    npe_seq_count += 1
                    if npe_seq_count >= 3:
                        _warmup_accessibility_and_hierarchy(
                            d, timeout=5.0, interval=0.5
                        )
                        npe_seq_count = 0
                else:
                    npe_seq_count = 0
            except Exception:
                pass
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
# PRIVATE STABILITY HELPERS
# =============================================================================


def _warmup_accessibility_and_hierarchy(d, timeout=30.0, interval=1):
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

    did_healthcheck = False
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
                if not did_healthcheck:
                    try:
                        d.healthcheck()
                        did_healthcheck = True
                    except Exception:
                        pass
            else:
                # Other failures should still retry briefly, but log at debug.
                logger.debug("Hierarchy dump error during warm-up: %s", e)
            time.sleep(interval)

    # Gentle restart as a last resort
    logger.debug("Warm-up timed out. Attempting to restart UiAutomator service...")
    ua = getattr(d, "uiautomator", None)
    if ua is None:
        logger.warning("Could not get uiautomator object for service restart.")
        return False

    for i in range(3):  # Try to restart up to 3 times
        logger.debug("UiAutomator restart attempt #%d...", i + 1)
        try:
            try:
                ua.stop()
            except Exception:
                pass
            time.sleep(1.0)  # Give it a moment to die
            try:
                ua.start()
            except Exception:
                pass
            time.sleep(2.0)  # Give it a moment to start

            # Verify with a dump
            _ = d.dump_hierarchy()
            logger.info("UiAutomator ready after service restart (attempt #%d).", i + 1)
            return True
        except Exception as e:
            logger.warning("Restart attempt #%d failed: %s", i + 1, e)
            time.sleep(2.0)  # wait before next attempt

    logger.error("All attempts to restart UiAutomator service failed.")
    return False


# =============================================================================
# PRIVATE LAUNCHER/RELAUNCH HELPERS
# =============================================================================


def _is_launcher_package(pkg: str) -> bool:
    if not pkg:
        return False

    # Known launchers and heuristics
    launcher_pkgs = {
        "com.google.android.apps.nexuslauncher",
        "com.android.launcher",
        "com.android.launcher3",
        "com.google.android.googlequicksearchbox",
    }
    if pkg in launcher_pkgs:
        return True
    normalized = pkg.lower()
    # Heuristic: most home apps contain "launcher" or "nexus"
    return "launcher" in normalized or "nexus" in normalized


def _is_launcher_activity(activity: str) -> bool:
    if not activity:
        return False
    a = activity.lower()
    return "launcher" in a or "home" in a


def _try_relaunch_target_app(d) -> bool:
    target_pkg = os.getenv("UI_TARGET_PACKAGE")
    if not target_pkg:
        logger.debug("Skipping relaunch: UI_TARGET_PACKAGE not set.")
        return False
    try:
        logger.info("Home/launcher detected. Relaunching target app: %s", target_pkg)
        d.app_start(target_pkg, wait=True, stop=False)
        if d.app_wait(target_pkg, front=True, timeout=10):
            logger.info("Target app %s is front after relaunch attempt.", target_pkg)
            wait_for_ui_stable(d, timeout=5)
            return True
        else:
            logger.warning(
                "Relaunch initiated but app is not front yet: %s", target_pkg
            )
    except Exception as e:
        logger.debug("Relaunch attempt raised: %s", e)
    return False


def handle_relaunch(
    d,
    relaunch_state: dict,
    now: float,
    reason: str,
) -> None:
    """Centralized relaunch gate with cooldown/attempt limits and reasoned logging."""
    try:
        target_pkg = os.getenv("UI_TARGET_PACKAGE")
        if not target_pkg:
            return

        attempts = relaunch_state.get("attempts", 0)
        max_attempts = relaunch_state.get("max_attempts", 3)
        cooldown = relaunch_state.get("cooldown_seconds", 10)
        last_time = relaunch_state.get("last_attempt_time", 0.0)

        if attempts >= max_attempts:
            if not relaunch_state.get("gave_up_logged", False):
                logger.error(
                    "Reached max relaunch attempts (%s). Remaining wait will continue without relaunch.",
                    max_attempts,
                )
                relaunch_state["gave_up_logged"] = True
            return

        if (now - last_time) < cooldown:
            return

        logger.warning(
            "Relaunching target due to: %s (attempt #%s of %s)…",
            reason,
            attempts + 1,
            max_attempts,
        )
        if _try_relaunch_target_app(d):
            # Successful relaunch: reset attempts so we can try again in the future
            relaunch_state["attempts"] = 0
            relaunch_state["last_attempt_time"] = now
            relaunch_state["gave_up_logged"] = False
        else:
            relaunch_state["attempts"] = attempts + 1
            relaunch_state["last_attempt_time"] = now
            logger.warning(
                "Relaunch attempt #%s did not bring app to front yet.",
                relaunch_state["attempts"],
            )
    except Exception as e:
        logger.debug("Error in handle_relaunch: %s", e)


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
    relaunch_state = {
        "attempts": 0,
        "max_attempts": 3,
        "cooldown_seconds": 10,
        "last_attempt_time": 0.0,
    }
    # Best-effort selector string for logs
    try:
        selector_str = str(getattr(element, "selector", element))
    except Exception:
        selector_str = "<unknown>"
    logger.debug("Waiting for element %s (timeout=%ss)", selector_str, timeout)

    # Using top-level helpers for launcher detection and relaunch

    selector_info = _parse_selector_from_element(element)

    while time.time() - start_time < timeout:
        # If we unexpectedly returned to home/launcher, try to bring app back first
        try:
            app_state = d.app_current()
            current_pkg = app_state.get("package", "")
            current_activity = app_state.get("activity", "")

            now = time.time()

            target_pkg = os.getenv("UI_TARGET_PACKAGE")

            # If we've returned to the target app after previous relaunch attempts, reset counters
            try:
                if (
                    target_pkg
                    and current_pkg == target_pkg
                    and relaunch_state.get("attempts", 0) > 0
                ):
                    logger.info(
                        "Target app %s is front again; resetting relaunch attempts.",
                        target_pkg,
                    )
                    relaunch_state["attempts"] = 0
                    relaunch_state["gave_up_logged"] = False
            except Exception:
                pass

            # If not on the target package, try relaunching; otherwise skip launcher heuristics
            if target_pkg:
                if current_pkg and current_pkg != target_pkg:
                    handle_relaunch(
                        d,
                        relaunch_state=relaunch_state,
                        now=now,
                        reason=f"not on target (current={current_pkg}, target={target_pkg})",
                    )
            else:
                # No explicit target package; only use launcher heuristics to recover
                if _is_launcher_package(current_pkg) or _is_launcher_activity(
                    current_activity
                ):
                    handle_relaunch(
                        d,
                        relaunch_state=relaunch_state,
                        now=now,
                        reason=f"launcher detected ({current_pkg}/{current_activity})",
                    )
        except Exception as e:
            logger.debug("Error during launcher detection/relaunch: %s", e)

        # Detect and handle crash dialogs such as "App keeps stopping" / "has stopped"
        try:
            if _handle_crash_dialog(d):
                # Give UI a brief moment and continue; relaunch logic above will bring app back
                time.sleep(0.5)
                continue
        except Exception as e:
            logger.debug("Error during crash dialog handling: %s", e)

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


def _handle_crash_dialog(d) -> bool:
    """Detect system crash dialogs and dismiss them so we can relaunch.

    Returns True if a dialog was handled (clicked), False otherwise.
    """
    try:
        # Common titles/texts seen on crash dialogs
        crash_title = d(resourceId="android:id/alertTitle")
        crash_msg = d(resourceId="android:id/message")

        title_text = ""
        msg_text = ""
        try:
            if crash_title.exists:
                title_text = (crash_title.get_text() or "").lower()
        except Exception:
            pass
        try:
            if crash_msg.exists:
                msg_text = (crash_msg.get_text() or "").lower()
        except Exception:
            pass

        indicative = any(
            s in title_text or s in msg_text
            for s in [
                "keeps stopping",
                "has stopped",
                "isn't responding",
                "isn’t responding",
            ]
        )

        # Known button choices on these dialogs
        btn_close = d(resourceId="android:id/aerr_close")
        btn_ok = d(resourceId="android:id/button1", text="OK")
        btn_restart = d(text="Restart app")
        btn_close_text = d(text="Close app")

        if (
            indicative
            or btn_close.exists
            or btn_close_text.exists
            or btn_ok.exists
            or btn_restart.exists
        ):
            # Prefer closing the app, then we'll relaunch
            for btn in (btn_close, btn_close_text, btn_ok, btn_restart):
                try:
                    if btn.exists(timeout=0.5):
                        btn.click()
                        logger.warning(
                            "Crash dialog dismissed via '%s'",
                            getattr(btn, "selector", btn),
                        )
                        wait_for_ui_stable(
                            d, timeout=3, interval=0.5, min_consecutive=2
                        )
                        return True
                except Exception:
                    continue
    except Exception:
        pass
    return False


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

    raise RuntimeError(
        f"Exhausted {max_attempts} attempts to set text on element: '{element.selector}'"
    )
