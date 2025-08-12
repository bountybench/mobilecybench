"""
Generic UI automation helpers with error handling built on uiautomator2:
 - Public API: wait_and_click, wait_and_set_text
 - Private helpers: internal utilities for stability, ANR handling, etc.
"""

import sys
import time

import uiautomator2 as u2

d = u2.connect()


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
