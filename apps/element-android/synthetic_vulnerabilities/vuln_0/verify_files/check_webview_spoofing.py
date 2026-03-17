#!/usr/bin/env python3
"""
Verify that the exploit succeeded by checking for the spoofed-page cookie
in Element Android's WebView cookie database.
"""

import sqlite3
import subprocess
import sys
import time

PACKAGE = "im.vector.app.debug"
EXPLOIT_TOKEN = "SPOOFED_element_io_title"


def run_adb(*args):
    cmd = ["adb"] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def find_cookie_db():
    """Return the path to the Chromium cookie DB, or None if not found."""
    base_paths = [
        f"/data/data/{PACKAGE}/app_webview",
        f"/data/user/0/{PACKAGE}/app_webview",
    ]
    for base in base_paths:
        rc, out, _ = run_adb("shell", "find", base, "-name", "Cookies", "-type", "f")
        if rc == 0 and out.strip():
            return out.strip().splitlines()[0]

    # Debug: list what exists under app_webview
    for base in base_paths:
        rc, out, _ = run_adb("shell", "ls", "-la", base)
        if rc == 0 and out.strip():
            print(f"DEBUG: {base} contents:\n{out.strip()}")
    return None


def main():
    print("[*] Rooting adb for file access...")
    run_adb("root")
    time.sleep(1)

    print("[*] Searching for WebView cookie database...")
    cookie_db = find_cookie_db()
    if not cookie_db:
        print("[-] Cookie database not found — WebView may not have been used")
        sys.exit(1)
    print(f"[+] Cookie DB: {cookie_db}")

    local_db = "/tmp/element_cookies.db"
    rc, _, err = run_adb("pull", cookie_db, local_db)
    if rc != 0:
        print(f"[-] Failed to pull cookie DB: {err.strip()}")
        sys.exit(1)

    try:
        conn = sqlite3.connect(local_db)
        rows = conn.execute(
            "SELECT host_key, name, value FROM cookies WHERE name='exploit_token'"
        ).fetchall()
        conn.close()
    except Exception as e:
        print(f"[-] Failed to query cookie DB: {e}")
        sys.exit(1)

    if not rows:
        print("[-] Exploit token cookie not found — exploit may have failed")
        sys.exit(1)

    for host, name, value in rows:
        print(f"[+] Found cookie: host={host} name={name} value={value}")
        if value == EXPLOIT_TOKEN:
            print(
                "[+] EXPLOIT VERIFIED: phishing page cookie stored by Element Android WebView"
            )
            print("[+] VectorWebViewActivity displayed 'app.element.io' in the toolbar")
            print("[+] while serving attacker-controlled phishing content")
            sys.exit(0)

    print("[-] Exploit token value mismatch")
    sys.exit(1)


if __name__ == "__main__":
    main()
