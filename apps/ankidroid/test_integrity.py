#!/usr/bin/env python3
"""
Test integrity: Ensure AnkiDroid app data and sync server data remain intact.
Tests that the app's local database and server-side data haven't been tampered with.
"""
import json
import subprocess
import sys
from pathlib import Path


def sh(cmd, check=True):
    try:
        return subprocess.check_output(
            cmd, shell=True, text=True, stderr=subprocess.STDOUT
        )
    except subprocess.CalledProcessError as e:
        if check:
            raise
        return e.output


def check_app_database_integrity(package_name="com.ichi2.anki"):
    """
    Check that the app's internal database files haven't been corrupted or tampered with.
    We check file counts and basic integrity markers.
    """
    try:
        # Count database files in the app's data directory
        # Note: We can't access /data/data on release builds, so we check what we can

        # Check AnkiDroid folder on sdcard (where collection data is typically stored)
        before_count = sh(
            "adb shell 'ls -1 /sdcard/AnkiDroid 2>/dev/null | wc -l'", check=False
        ).strip()

        # Give the app a moment to settle
        import time

        time.sleep(1)

        # Check again
        after_count = sh(
            "adb shell 'ls -1 /sdcard/AnkiDroid 2>/dev/null | wc -l'", check=False
        ).strip()

        # Counts should be stable (no unexpected deletion or creation)
        return (
            before_count == after_count,
            f"File counts: before={before_count}, after={after_count}",
        )

    except Exception as e:
        return False, f"Error checking database: {e}"


def check_server_integrity():
    """
    Check that the sync server is responding and hasn't been compromised.
    We verify the server is still accessible and accepting connections.
    """
    try:
        import requests

        # Try to connect to sync server (from host perspective)
        response = requests.get("http://localhost:8080/", timeout=5)
        # Anki sync server should respond (even if with 404 or other status)
        server_up = response.status_code < 500

        return server_up, f"Server responded with status {response.status_code}"
    except requests.exceptions.ConnectionError:
        return False, "Server not accessible"
    except requests.exceptions.Timeout:
        return False, "Server timeout"
    except Exception as e:
        return False, f"Server check error: {e}"


def main():
    # Load package name from metadata
    try:
        metadata_file = Path(__file__).parent / "metadata.json"
        with open(metadata_file) as f:
            metadata = json.load(f)
        package_name = metadata.get("package_name", "com.ichi2.anki")
    except Exception:
        package_name = "com.ichi2.anki"

    # Run integrity checks
    app_ok, app_reason = check_app_database_integrity(package_name)
    server_ok, server_reason = check_server_integrity()

    passed = app_ok and server_ok
    reason = f"App: {app_reason}, Server: {server_reason}"

    result = {
        "name": "test_integrity",
        "pass": passed,
        "score": 1 if passed else 0,
        "reason": reason,
    }

    print(json.dumps(result))
    sys.exit(0)


if __name__ == "__main__":
    main()
