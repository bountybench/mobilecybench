#!/usr/bin/env python3
"""
Walk through the OwnTracks first-launch welcome wizard.

Screens: Welcome → Connection setup → Location permissions → Notification permissions → Done
Action:  NEXT    → NEXT             → NEXT                → NEXT                      → DONE

Usage:
    python welcome_wizard.py
"""
import sys
import time

import uiautomator2 as u2

PACKAGE = "org.owntracks.android"
SCRIPT_NAME = "welcome_wizard"

# Resource IDs
BTN_NEXT = f"{PACKAGE}:id/btn_next"
BTN_DONE = f"{PACKAGE}:id/btn_done"
FAB_MY_LOCATION = f"{PACKAGE}:id/fabMyLocation"


def log(msg):
    print(f"[{SCRIPT_NAME}] {msg}", file=sys.stderr)


def main():
    d = u2.connect()

    # Ensure app is in foreground
    current = d.app_current()
    if current.get("package") != PACKAGE:
        log(f"App not in foreground (current: {current.get('package')}), launching...")
        d.app_start(PACKAGE, wait=True)
        time.sleep(3)

    # Check if wizard is showing (btn_next present)
    if not d(resourceId=BTN_NEXT).wait(timeout=5):
        # Maybe wizard was already completed
        if d(resourceId=FAB_MY_LOCATION).exists:
            log("Already on MapActivity — wizard was previously completed")
            return
        log("ERROR: Neither welcome wizard nor MapActivity found")
        sys.exit(1)

    # Click NEXT through 4 wizard screens
    for step in range(1, 5):
        btn = d(resourceId=BTN_NEXT)
        if not btn.wait(timeout=5):
            log(f"Step {step}: NEXT button not found — wizard may have fewer screens")
            break
        log(f"Step {step}: clicking NEXT")
        btn.click()
        time.sleep(1)

    # Final screen: click DONE
    btn = d(resourceId=BTN_DONE)
    if btn.wait(timeout=5):
        log("Clicking DONE")
        btn.click()
        time.sleep(2)
    else:
        log("WARNING: DONE button not found")

    # Verify we landed on MapActivity
    if d(resourceId=FAB_MY_LOCATION).wait(timeout=10):
        log("Welcome wizard completed — on MapActivity")
    else:
        log("ERROR: Did not reach MapActivity after wizard")
        sys.exit(1)


if __name__ == "__main__":
    main()
