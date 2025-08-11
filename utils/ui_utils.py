import sys
import time

import uiautomator2 as u2

d = u2.connect()


def wait_and_click_text(text, timeout=45, exit_on_error=True):
    if d(text=text).wait(timeout=timeout):
        d(text=text).click_exists(timeout=3)
    else:
        print(
            f"[ERROR] Could not find text: '{text}' within {timeout}s", file=sys.stderr
        )
        print(d.dump_hierarchy(), file=sys.stderr)
        if exit_on_error:
            exit(1)
    wait_for_ui_stable(timeout=5)


def wait_and_click_desc(desc, timeout=45, exit_on_error=True):
    if d(description=desc).wait(timeout=timeout):
        d(description=desc).click_exists(timeout=3)
    else:
        print(
            f"[ERROR] Could not find description: '{desc}' within {timeout}s",
            file=sys.stderr,
        )
        print(d.dump_hierarchy(), file=sys.stderr)
        if exit_on_error:
            exit(1)
    wait_for_ui_stable(timeout=5)


def wait_for_ui_stable(timeout=10, interval=0.5):
    """
    Wait until the UI hierarchy stops changing.
    """
    prev_hierarchy = None
    start = time.time()

    while time.time() - start < timeout:
        current_hierarchy = d.dump_hierarchy(compressed=True)
        if current_hierarchy == prev_hierarchy:
            return True
        prev_hierarchy = current_hierarchy
        time.sleep(interval)
    return False
