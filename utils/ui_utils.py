"""
Concise uiautomator2 helpers for reliable clicking and text entry without sleeps.
Public API: initialize_ui_automation, wait_and_click, wait_and_set_text
"""

import re
import subprocess
import sys
import time

import uiautomator2 as u2

# =============================================================================
# UI AUTOMATION INITIALIZATION
# =============================================================================


def initialize_ui_automation(max_retries=3, retry_delay=5):
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
                print(f"[WARN] 'adb devices' failed: {result.stderr}", file=sys.stderr)
                return False
            lines = [line for line in result.stdout.splitlines()[1:] if line.strip()]
            return any("\tdevice" in line for line in lines)
        except Exception as e:
            print(f"[WARN] Could not run 'adb devices': {e}", file=sys.stderr)
            return False

    def _adb_wait_for_device(timeout_seconds: int) -> None:
        """Block on 'adb wait-for-device' instead of sleeping between retries."""
        try:
            subprocess.run(["adb", "wait-for-device"], timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            print(
                f"[WARN] 'adb wait-for-device' timed out after {timeout_seconds}s",
                file=sys.stderr,
            )
        except Exception as e:
            print(f"[WARN] 'adb wait-for-device' failed: {e}", file=sys.stderr)

    for attempt_index in range(1, max_retries + 1):
        print(
            f"[INFO] Connecting to device (attempt {attempt_index}/{max_retries})…",
            file=sys.stderr,
        )

        if not _adb_has_devices():
            print(
                "[ERROR] No ADB devices detected. Is a device/emulator connected and authorized?",
                file=sys.stderr,
            )
            if attempt_index < max_retries:
                _adb_wait_for_device(retry_delay)
                continue
            _fatal(None, "No devices detected by ADB after all attempts")

        try:
            device = u2.connect()
            # Touch the device to ensure the connection is usable
            _ = device.device_info  # may raise if not connected
            print("[INFO] Connected to device.", file=sys.stderr)

            return device
        except Exception as e:
            print(f"[WARN] Connection failed: {e}", file=sys.stderr)
            if attempt_index < max_retries:
                _adb_wait_for_device(retry_delay)
                continue
            _fatal(
                None, f"Failed to connect to device after {max_retries} attempts: {e}"
            )

        # Configure a sensible implicit wait to reduce flakiness across helpers
        try:
            device.implicitly_wait(5.0)
        except Exception:
            # Not fatal if the backend does not support implicit waits
            pass


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
            print(f"[ERROR] {message}", file=sys.stderr)
            return False

    if not element.click_exists(
        timeout=5
    ):  # Try clicking element; raise error/fatal if failed
        message = f"Could not click element: '{element.selector}'"
        if exit_on_error:
            _fatal(d, message)
        else:
            print(f"[ERROR] {message}", file=sys.stderr)
            return False

    # Clicked element; return True
    print(f"[INFO] Clicked element {element.selector}", file=sys.stderr)

    return True


def wait_and_set_text(d, element, text, timeout=180, exit_on_error=True):
    """Wait for an input element, focus it, set text, then handle IME action."""
    if not _wait_for_element(d, element, timeout=timeout):
        message = f"Could not find element: '{element.selector}' within {timeout}s"
        if exit_on_error:
            _fatal(d, message)
        else:
            print(f"[ERROR] {message}", file=sys.stderr)
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
            print(f"[ERROR] {message}", file=sys.stderr)
            return False

    print(f"[INFO] Set text to {text}", file=sys.stderr)
    _handle_keyboard_action(d)

    return True


def wait_for_ui_stable(d, timeout=5, interval=0.5, min_consecutive=3):
    """Prefer device idle; fall back to lightweight hierarchy-diff stability check."""
    prev_hierarchy = None
    same_count = 0
    start = time.time()

    # Prefer device-level idle detection if available to avoid arbitrary sleeps
    try:
        if d.wait_idle(timeout=int(timeout * 1000), idle=int(interval * 1000)):
            return True
    except Exception as e:
        print(
            f"[WARN] wait_idle not available or failed; falling back to hierarchy diff: {e}",
            file=sys.stderr,
        )

    while time.time() - start < timeout:
        try:
            current_hierarchy = d.dump_hierarchy()
        except Exception as e:
            print(
                f"[WARN] Failed to dump UI hierarchy during stability check: {e}",
                file=sys.stderr,
            )
            continue

        # Count consecutive identical dumps
        if prev_hierarchy is not None and current_hierarchy == prev_hierarchy:
            same_count += 1
        else:
            same_count = 1

        prev_hierarchy = current_hierarchy

        # Return True if the UI has stabilized for at least min_consecutive samples
        if same_count >= min_consecutive:
            return True

    elapsed = time.time() - start
    print(
        f"[WARN] UI did not stabilize within {elapsed:.1f}s (required {min_consecutive} consecutive identical dumps).",
        file=sys.stderr,
    )
    return False


# =============================================================================
# PRIVATE STABILITY HELPERS
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

    selector_info = _parse_selector_from_element(element)

    if not element.exists:
        _try_scroll_into_view(d, selector_info)

    while time.time() - start_time < timeout:
        if not _handle_anr(
            d, max_anrs=5, timeout=1, target_element=element
        ):  # Failed to unfreeze system UI; abort early
            return False

        # Prefer element-driven wait rather than arbitrary sleep
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
                print(
                    f"[DEBUG] ANR dialog #{anr_count} detected. Clicking 'Wait' to continue...",
                    file=sys.stderr,
                )
                wait_button.click()

                # Wait for either target element or UI stability
                if target_element is not None:
                    print(
                        f"[DEBUG] Waiting for target element '{target_element.selector}' to appear after ANR...",
                        file=sys.stderr,
                    )
                    if target_element.wait(timeout=5):
                        print(
                            f"[DEBUG] Target element '{target_element.selector}' appeared successfully after ANR.",
                            file=sys.stderr,
                        )
                        break  # Target element found - exit ANR loop
                    else:
                        print(
                            f"[DEBUG] Target element '{target_element.selector}' did not appear after ANR dismissal.",
                            file=sys.stderr,
                        )
                        continue  # Continue checking for more ANRs
                else:
                    print(
                        "[DEBUG] Waiting for UI to stabilize after ANR...",
                        file=sys.stderr,
                    )
                    wait_for_ui_stable(d, timeout=5)
            else:
                break  # No ANR dialog found
        except Exception as e:
            print(
                f"[WARN] Could not click ANR 'Wait' button (it may have disappeared): {e}"
            )
            break

    # Reached max ANR limit: log summary and report False (non-fatal)
    if anr_count == max_anrs:
        print(
            f"[ERROR] Could not fully handle ANR dialog(s): reached maximum limit of {max_anrs}.",
            file=sys.stderr,
        )
        return False

    if anr_count > 0:
        print(
            f"[WARN] Handled {anr_count} consecutive ANR dialog(s) until system UI unfreeze.",
            file=sys.stderr,
        )

    return True


# =============================================================================
# ERROR HANDLING HELPERS
# =============================================================================


def _fatal(d, message):
    """
    Centralized fatal error handler: log message, dump UI hierarchy if possible,
    then exit the process with non-zero code.

    Args:
        d: Device object (may be None)
        message: Error message to print
    """
    print(f"[FATAL] {message}", file=sys.stderr)
    try:
        if d is not None:
            print(d.dump_hierarchy(), file=sys.stderr)
    except Exception as dump_err:
        print(f"[WARN] Failed to dump UI hierarchy: {dump_err}", file=sys.stderr)
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
            print("[INFO] Clicked keyboard Done button", file=sys.stderr)
            return True
    except Exception as e:
        print(f"[WARN] Could not click keyboard Done button: {e}", file=sys.stderr)

    # Method 2: Try clicking the keyboard action button
    try:
        if d(
            resourceId="com.google.android.inputmethod.latin:id/key_pos_ime_action"
        ).exists(timeout=1):
            d(
                resourceId="com.google.android.inputmethod.latin:id/key_pos_ime_action"
            ).click()
            print("[INFO] Clicked keyboard action button", file=sys.stderr)
            return True
    except Exception as e:
        print(f"[WARN] Could not click keyboard action button: {e}", file=sys.stderr)

    # Method 3: Try pressing Enter key
    try:
        d.press("enter")
        print("[INFO] Pressed Enter key", file=sys.stderr)
        return True
    except Exception as e:
        print(f"[WARN] Could not press Enter key: {e}", file=sys.stderr)

    print("[WARN] All keyboard action methods failed", file=sys.stderr)
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
            print(
                f"[INFO] Set text attempt {attempt_index} succeeded for {element.selector}",
                file=sys.stderr,
            )
            return True
        except Exception as set_error:
            print(
                f"[WARN] set_text attempt {attempt_index} failed: {set_error}",
                file=sys.stderr,
            )
            # Avoid arbitrary sleep; allow the device to settle using wait_idle
            try:
                d.wait_idle(timeout=1000, idle=500)
            except Exception:
                # If wait_idle isn't available, proceed to next attempt without sleeping
                pass

    raise RuntimeError(
        f"Exhausted {max_attempts} attempts to set text on element: '{element.selector}'"
    )
