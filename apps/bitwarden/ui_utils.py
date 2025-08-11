"""
Generic UI automation helpers built on uiautomator2:
 - Public API: initialize_ui_automation, wait_and_click, wait_and_set_text
 - Private helpers: internal utilities for stability, ANR handling, etc.
Bitwarden-specific workflows are defined in bw_workflows.py.
"""

import re
import subprocess
import sys
import time

import uiautomator2 as u2

# =============================================================================
# PUBLIC UI API
# =============================================================================


def initialize_ui_automation(max_retries=3, retry_delay=5):
    """
    Standardized UI automation initialization with device connection.

    Args:
        max_retries: Maximum connection attempts
        retry_delay: Seconds between retry attempts

    Returns:
        Device object if successful
    """
    for attempt in range(max_retries):
        try:
            print(
                f"[DEBUG] Attempting to connect to device (attempt {attempt + 1}/{max_retries})..."
            )

            # Check if ADB is working
            try:
                result = subprocess.run(
                    ["adb", "devices"], capture_output=True, text=True, timeout=10
                )
                if result.returncode != 0:
                    print(f"[WARN] ADB devices command failed: {result.stderr}")
                    continue

                devices = result.stdout.strip().split("\n")[1:]  # Skip header
                connected_devices = [d for d in devices if d.strip() and "device" in d]

                if not connected_devices:
                    print("[WARN] No devices found via ADB")
                    continue

                print(
                    f"[DEBUG] Found {len(connected_devices)} device(s): {connected_devices}"
                )

            except subprocess.TimeoutExpired:
                print("[WARN] ADB devices command timed out")
                continue
            except Exception as e:
                print(f"[WARN] ADB devices command failed: {e}")
                continue

            # Try to connect with uiautomator2
            d = u2.connect()

            # Test the connection by trying to get device info
            try:
                device_info = d.device_info
                print(
                    f"Successfully connected to device: {device_info.get('model', 'Unknown')}"
                )
                return d
            except Exception as e:
                print(f"[WARN] Device connection test failed: {e}")
                continue

        except Exception as e:
            print(f"[WARN] Connection attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)

    # If unable to connect prevents script execution, exit via centralized fatal handler
    _fatal(None, "Failed to connect to device after all attempts")


# =============================================================================
# PUBLIC UI ELEMENT INTERACTION FUNCTIONS
# =============================================================================


def wait_and_click(d, element, timeout=180):
    """
    Waits for an element and clicks it, with continuous ANR handling.

    Args:
        d: Device object
        element: UI element to wait for and click
        timeout: Maximum time to wait for element
    """
    if not _wait_for_element(d, element, timeout=timeout):
        _fatal(d, f"Could not find element: '{element.selector}' within {timeout}s")

    try:
        element.click_exists(timeout=3)
        print(f"[INFO] Clicked element {element.selector}")
        _wait_for_ui_stable(d)
    except Exception as e:
        _fatal(d, f"Could not click element: '{element.selector}': {e}")


def wait_and_set_text(d, element, text, timeout=180):
    """
    Waits for an EditText element and sets its text, with continuous ANR handling.

    Args:
        d: Device object
        element: UI element to wait for and set text on
        text: Text to set
        timeout: Maximum time to wait for element
    """
    if not _wait_for_element(d, element, timeout=timeout):
        _fatal(d, f"Could not find element: '{element.selector}' within {timeout}s")

    # Use robust text entry with retries and scroll support
    try:
        _robust_set_text(d, element, text, max_attempts=3)
        print(f"[INFO] Set text to {text}")
        _handle_keyboard_action(d)
        _wait_for_ui_stable(d)
    except Exception as e:
        _fatal(d, f"Failed to set text on element: '{element.selector}': {e}")


# =============================================================================
# PRIVATE HELPERS
# =============================================================================


def _wait_for_element(d, element, timeout=180):
    """
    Wait for an element to exist while continuously handling potential ANR dialogs.

    Args:
        d: Device object
        element: UI element to wait for
        timeout: Maximum time to wait in seconds

    Returns:
        True if the element exists within the timeout, otherwise False
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        _handle_anr(d, max_anrs=5, timeout=1, target_element=element)
        if element.exists:
            return True
        time.sleep(1)
    return False


def _wait_for_ui_stable(d, timeout=10, interval=0.5):
    """
    Waits until the UI hierarchy stops changing.

    Args:
        d: Device object
        timeout: Maximum time to wait for stability
        interval: Time between stability checks

    Returns:
        True if UI stabilized, False if timeout reached
    """
    prev_hierarchy = None
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

        if current_hierarchy == prev_hierarchy:
            print("[INFO] UI is stable")
            return True
        prev_hierarchy = current_hierarchy
        time.sleep(interval)
    print("[WARN] UI did not stabilize within the timeout.", file=sys.stderr)
    return False


def _handle_anr(d, max_anrs=5, timeout=3, target_element=None):
    """
    Handles consecutive "Application Not Responding" (ANR) dialogs by clicking "Wait".

    Args:
        d: Device object
        max_anrs: Maximum number of consecutive ANR dialogs to handle
        timeout: Timeout for checking each ANR dialog
        target_element: Optional element to wait for after dismissing ANR

    Returns:
        True if ANR dialogs were handled, False if none found
    """
    anr_count = 0
    for i in range(max_anrs):
        wait_button = d(resourceId="android:id/aerr_wait")

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
                            f"[WARN] Target element '{target_element.selector}' did not appear after ANR dismissal."
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

    # Fatal error if we hit the max ANR limit
    if anr_count == max_anrs:
        _fatal(
            d, f"Could not handle ANR dialog(s) - reached maximum limit of {max_anrs}."
        )

    if anr_count > 0:
        print(f"[INFO] Handled {anr_count} consecutive ANR dialog(s).")
        return True

    return False


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
    Parses a uiautomator2 element's selector string into a dictionary of key/value pairs.
    Example input: "Selector [resourceId='LoginPasswordEntry']"
    Returns: dict like {"resourceId": "LoginPasswordEntry"}
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
            scrollable.scroll.to(resourceId=selector_info["resourceId"])  # type: ignore
            return True
        if "text" in selector_info:
            scrollable.scroll.to(text=selector_info["text"])  # type: ignore
            return True
        return False
    except Exception:
        return False


def _robust_set_text(d, element, text, max_attempts=3):
    """
    Tries to set text into an element with retries, ANR handling, and optional scrolling.
    Returns True on success, False on failure after retries.
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
    print(f"[ERROR] {message}", file=sys.stderr)
    try:
        if d is not None:
            print(d.dump_hierarchy(), file=sys.stderr)
    except Exception as dump_err:
        print(f"[WARN] Failed to dump UI hierarchy: {dump_err}", file=sys.stderr)
    sys.exit(1)
