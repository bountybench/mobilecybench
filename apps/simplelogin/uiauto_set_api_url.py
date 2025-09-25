#!/usr/bin/env python3
"""
SimpleLogin UI Automation: set API URL via in-app "Change API URL" flow.

Mirrors Joplin's approach using uiautomator2 for consistency across apps.
Exits 0 on success; non-zero on failure.
"""

import argparse
import json
import os
import sys
import time

try:
    import uiautomator2 as u2
except Exception as e:
    print(f"[ERROR] uiautomator2 not available: {e}", file=sys.stderr)
    sys.exit(2)


def load_metadata(base_dir: str):
    meta_path = os.path.join(base_dir, "metadata.json")
    with open(meta_path, "r") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(
        description="Set SimpleLogin API URL via UI automation"
    )
    parser.add_argument(
        "--url", help="API URL to set (default from metadata or 10.0.2.2:7777)"
    )
    parser.add_argument("--pkg", help="Package id (default from metadata)")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    meta = load_metadata(base_dir)

    pkg = args.pkg or meta.get("package_name", "io.simplelogin.android.fdroid")
    api_url = args.url or meta.get("emulator_server") or "http://10.0.2.2:7777"

    d = u2.connect()

    # Launch app
    try:
        d.app_start(pkg, use_monkey=True)
        if not d.app_wait(pkg, front=True, timeout=5.0):
            print("[ERROR] App not in foreground after start", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Failed to start app: {e}", file=sys.stderr)
        sys.exit(1)

    # Attempt to find and tap the "Change API URL" button
    try:
        # Prefer resource-id if stable, else fallback to text
        btn = d(resourceId=f"{pkg}:id/changeApiUrlButton")
        if not btn.exists:
            btn = d(text="Change API URL")
        if not btn.exists:
            # Give UI a moment and retry once
            time.sleep(1)
            d.app_wait(pkg, front=True, timeout=2.0)
            btn = d(resourceId=f"{pkg}:id/changeApiUrlButton")
            if not btn.exists:
                btn = d(text="Change API URL")
        if not btn.exists:
            print("[ERROR] Could not find 'Change API URL' button", file=sys.stderr)
            sys.exit(1)
        btn.click_exists(timeout=2.0)
    except Exception as e:
        print(f"[ERROR] Failed clicking Change API URL: {e}", file=sys.stderr)
        sys.exit(1)

    # Enter URL in the EditText
    try:
        field = d(className="android.widget.EditText")
        if not field.exists:
            time.sleep(0.5)
            field = d(className="android.widget.EditText")
        if not field.exists:
            print("[ERROR] Could not find API URL EditText", file=sys.stderr)
            sys.exit(1)
        field.set_text(api_url)
        time.sleep(0.2)
        # Try clicking a positive button if present, else press enter
        ok = d(textMatches="OK|Save|Apply")
        if ok.exists:
            ok.click_exists(timeout=2.0)
        else:
            d.press("enter")
    except Exception as e:
        print(f"[ERROR] Failed setting API URL: {e}", file=sys.stderr)
        sys.exit(1)

    # Force-stop to ensure app reloads prefs on next start
    try:
        d.app_stop(pkg)
    except Exception:
        pass

    print(f"[OK] API URL set to {api_url}")
    sys.exit(0)


if __name__ == "__main__":
    main()
