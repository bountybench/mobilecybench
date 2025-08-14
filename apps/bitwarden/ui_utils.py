"""
Generic UI automation helpers with error handling built on uiautomator2:
 - Public API: wait_and_click, wait_and_set_text
 - Private helpers: internal utilities for stability, ANR handling, etc.
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
    """
    Connect to an Android device for UI automation with concise, helpful errors.

    - Verifies that ADB sees at least one device (best-effort).
    - Attempts to connect via uiautomator2 up to max_retries.
    - Returns the connected device on success; otherwise exits fatally.

    Args:
        max_retries: Maximum connection attempts
        retry_delay: Seconds to wait between attempts

    Returns:
        A uiautomator2 Device instance on success.
    """

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

    for attempt_index in range(1, max_retries + 1):
        print(f"[INFO] Connecting to device (attempt {attempt_index}/{max_retries})…")

        if not _adb_has_devices():
            print(
                "[ERROR] No ADB devices detected. Is a device/emulator connected and authorized?",
                file=sys.stderr,
            )
            if attempt_index < max_retries:
                time.sleep(retry_delay)
                continue
            _fatal(None, "No devices detected by ADB after all attempts")

        try:
            device = u2.connect()
            # Touch the device to ensure the connection is usable
            _ = device.device_info  # may raise if not connected
            print("[INFO] Connected to device.")
            return device
        except Exception as e:
            print(f"[WARN] Connection failed: {e}", file=sys.stderr)
            if attempt_index < max_retries:
                time.sleep(retry_delay)
                continue
            _fatal(
                None, f"Failed to connect to device after {max_retries} attempts: {e}"
            )


# =============================================================================
# PUBLIC UI ELEMENT INTERACTION FUNCTIONS
# =============================================================================


def wait_and_click(d, element, timeout=180, exit_on_error=True):
    """
    Wait for a UI element to appear, then click it. Handles ANR dialogs throughout.

    Args:
        d: Device object
        element: UI element selector, e.g., d(text="..."), d(description="..."), d(resourceId="...")
        timeout: Maximum time to wait for the element to appear
        exit_on_error: If True, exits the process on failure; otherwise returns False

    Returns:
        True on success, False on failure when exit_on_error is False.

    Usage examples:
        # Click by text
        wait_and_click(d, d(text="Continue"))

        # Click by content description
        wait_and_click(d, d(description="Navigate up"))

        # Click by resourceId
        wait_and_click(d, d(resourceId="com.example:id/confirm_button"))
    """
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
        timeout=3
    ):  # Try clicking element; raise error/fatal if failed
        message = f"Could not click element: '{element.selector}'"
        if exit_on_error:
            _fatal(d, message)
        else:
            print(f"[ERROR] {message}", file=sys.stderr)
            return False

    # Clicked element; return True
    print(f"[INFO] Clicked element {element.selector}")
    _wait_for_ui_stable(d)

    return True


def wait_and_set_text(d, element, text, timeout=180, exit_on_error=True):
    """
    Wait for an input element and set its text. Handles ANR dialogs and retries.

    Args:
        d: Device object
        element: UI element to wait for and set text on (e.g., d(text=...), d(resourceId=...))
        text: Text to set
        timeout: Maximum time to wait for element
        exit_on_error: If True, exits the process on failure; otherwise returns False

    Returns:
        True on success, False on failure when exit_on_error is False.
    """
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
        element.click_exists(timeout=3)
        _robust_set_text(d, element, text, max_attempts=3)
    except Exception as e:
        message = f"Failed to set text on element: '{element.selector}': {e}"
        if exit_on_error:
            _fatal(d, message)
        else:
            print(f"[ERROR] {message}", file=sys.stderr)
            return False

    print(f"[INFO] Set text to {text}")
    _handle_keyboard_action(d)
    _wait_for_ui_stable(d)
    return True


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

    while time.time() - start_time < timeout:
        if not _handle_anr(
            d, max_anrs=5, timeout=1, target_element=element
        ):  # Failed to unfreeze system UI; abort early
            return False
        if element.exists:  # Element found; return True
            return True
        time.sleep(1)

    return False


def _handle_anr(d, max_anrs=5, timeout=3, target_element=None):
    """
    Handles consecutive "Application Not Responding" (ANR) dialogs by clicking "Wait" up to max_anrs times.

    Args:
        d: Device object
        max_anrs: Maximum number of consecutive ANR dialogs to handle
        timeout: Timeout for checking each ANR dialog
        target_element: Optional element to wait for after dismissing ANR

    Returns:
        bool: True if the maximum number of consecutive ANRs was not reached,
              False otherwise (system likely frozen).
    """
    anr_count = 0
    wait_button = d(resourceId="android:id/aerr_wait")

    for _ in range(max_anrs):
        try:
            if wait_button.exists(timeout=timeout):
                anr_count += 1
                print(
                    f"[DEBUG] ANR dialog #{anr_count} detected. Clicking 'Wait' to continue..."
                )
                wait_button.click()

                # Wait for either target element or UI stability
                if target_element is not None:
                    print(
                        f"[DEBUG] Waiting for target element '{target_element.selector}' to appear after ANR..."
                    )
                    if target_element.wait(timeout=10):
                        print(
                            f"[DEBUG] Target element '{target_element.selector}' appeared successfully after ANR."
                        )
                        break  # Target element found - exit ANR loop
                    else:
                        print(
                            f"[DEBUG] Target element '{target_element.selector}' did not appear after ANR dismissal."
                        )
                        continue  # Continue checking for more ANRs
                else:
                    print("[DEBUG] Waiting for UI to stabilize after ANR...")
                    _wait_for_ui_stable(d, timeout=10)
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
            f"[WARN] Handled {anr_count} consecutive ANR dialog(s) until system UI unfreeze."
        )

    return True


def _wait_for_ui_stable(d, timeout=10, interval=0.5, min_consecutive=3):
    """
    Wait until the UI hierarchy appears stable by observing identical dumps
    for a number of consecutive samples.

    Args:
        d: Device object
        timeout: Maximum time to wait for stability
        interval: Time between stability checks
        min_consecutive: Number of consecutive identical hierarchy dumps
            required to consider the UI stable (default: 2)

    Returns:
        True if UI stabilized within timeout, False otherwise
    """
    prev_hierarchy = None
    same_count = 0
    start = time.time()

    while time.time() - start < timeout:
        try:
            current_hierarchy = d.dump_hierarchy(compressed=True)
        except Exception as e:
            print(
                f"[WARN] Failed to dump UI hierarchy during stability check: {e}",
                file=sys.stderr,
            )
            time.sleep(interval)
            continue

        # Count consecutive identical dumps
        if prev_hierarchy is not None and current_hierarchy == prev_hierarchy:
            same_count += 1
        else:
            same_count = 1

        prev_hierarchy = current_hierarchy

        # Return True if the UI has stabilized for at least min_consecutive samples (UI is stable)
        if same_count >= min_consecutive:
            return True

        time.sleep(interval)

    elapsed = time.time() - start
    print(
        f"[WARN] UI did not stabilize within {elapsed:.1f}s (required {min_consecutive} consecutive identical dumps).",
        file=sys.stderr,
    )
    return False


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
    """
    Handles keyboard action (Done/Enter) with multiple fallback methods.

    Args:
        d: Device object

    Returns:
        True if keyboard action was successful, False otherwise
    """
    # Handle any ANRs before keyboard interaction
    _handle_anr(d, max_anrs=5, timeout=1, target_element=None)

    # Method 1: Try clicking the keyboard Done button
    try:
        if d(description="Done").exists(timeout=1):
            d(description="Done").click()
            print("[INFO] Clicked keyboard Done button")
            return True
    except Exception as e:
        print(f"[WARN] Could not click keyboard Done button: {e}")

    # Method 2: Try clicking the keyboard action button
    try:
        if d(
            resourceId="com.google.android.inputmethod.latin:id/key_pos_ime_action"
        ).exists(timeout=1):
            d(
                resourceId="com.google.android.inputmethod.latin:id/key_pos_ime_action"
            ).click()
            print("[INFO] Clicked keyboard action button")
            return True
    except Exception as e:
        print(f"[WARN] Could not click keyboard action button: {e}")

    # Method 3: Try pressing Enter key
    try:
        d.press("enter")
        print("[INFO] Pressed Enter key")
        return True
    except Exception as e:
        print(f"[WARN] Could not press Enter key: {e}")

    print("[WARN] All keyboard action methods failed")
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

            element.click_exists(timeout=2)
            element.set_text(text)
            print(
                f"[INFO] Set text attempt {attempt_index} succeeded for {element.selector}"
            )
            return True
        except Exception as set_error:
            print(f"[WARN] set_text attempt {attempt_index} failed: {set_error}")
            # Try to scroll into view for the next attempt
            _try_scroll_into_view(d, selector_info)
            # Small pause before retry
            time.sleep(0.5)

    raise RuntimeError(
        f"Exhausted {max_attempts} attempts to set text on element: '{element.selector}'"
    )