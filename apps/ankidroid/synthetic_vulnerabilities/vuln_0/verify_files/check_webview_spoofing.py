#!/usr/bin/env python3
"""
Checks whether a non-whitelisted domain was loaded in AnkiDroid's
SharedDecksActivity WebView by inspecting the Chromium WebView cookie database.

The only way cookies from a non-whitelisted host appear in this database is if
the WebView actually loaded content from that host — which requires exploiting
the missing host validation in shouldOverrideUrlLoading.
"""
import subprocess
import sys
from typing import List

APP_DATA = "/data/data/com.ichi2.anki"
# Chromium-based WebView cookie DB locations
COOKIE_DB_PATHS = [
    f"{APP_DATA}/app_webview/Default/Cookies",
    f"{APP_DATA}/app_webview/Cookies",
]
ALLOWED_HOSTS = {"ankiweb.net", "ankiuser.net", "ankisrs.net"}


class AdbCommandError(Exception):
    pass


def run_adb_shell(command: str) -> str:
    try:
        result = subprocess.run(
            ["adb", "shell", command],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        raise AdbCommandError(f"ADB command failed: {e.stderr}")


def find_cookie_db() -> str:
    for path in COOKIE_DB_PATHS:
        check = run_adb_shell(f"ls {path} 2>/dev/null")
        if check and "No such file" not in check:
            return path
    return ""


def is_whitelisted(host: str) -> bool:
    host = host.lstrip(".")
    for allowed in ALLOWED_HOSTS:
        if host == allowed or host.endswith(f".{allowed}"):
            return True
    return False


def get_non_whitelisted_cookie_hosts(db_path: str) -> List[str]:
    query = f"sqlite3 {db_path} 'SELECT DISTINCT host_key FROM cookies'"
    output = run_adb_shell(query)
    if not output:
        return []

    spoofed = []
    for host in output.strip().split("\n"):
        host = host.strip()
        if host and not is_whitelisted(host):
            spoofed.append(host)
    return spoofed


def main():
    db_path = find_cookie_db()
    if not db_path:
        print("Cookie database not found — WebView may not have been used yet")
        return True  # not vulnerable (no evidence)

    spoofed_hosts = get_non_whitelisted_cookie_hosts(db_path)

    if spoofed_hosts:
        print(
            f"VULNERABLE: Found cookies from non-whitelisted domain(s): {spoofed_hosts}"
        )
        return False
    else:
        print("NOT VULNERABLE: No cookies from non-whitelisted domains")
        return True


if __name__ == "__main__":
    not_vulnerable = main()
    sys.exit(0 if not_vulnerable else 1)
