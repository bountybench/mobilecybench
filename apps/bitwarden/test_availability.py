"""
test_availability.py checks if the app is running and the server is healthy.

It checks:
- Server-side checks:
    - If the docker-compose service is running (check for Vaultwarden and DB)
    - If the server's /alive endpoint returns 200 OK
- Client-side (app) checks:
    - If the app can be launched and its UI is responsive
    - If crash or ANR for Bitwarden is detected in recent logs
"""

import os
import subprocess
import sys
import time
import urllib.request

import uiautomator2 as u2

from util import adb

SERVER_SERVICE = "vaultwarden"
DB_SERVICE = "db"
SERVER_URL = "http://localhost:8080/alive"
APP_PACKAGE = "com.x8bit.bitwarden.dev"


"""
check_container_running()
- Takes in the name of the service to check
- Returns boolean of whether the docker-compose service is running
"""


def check_container_running(service_name: str) -> bool:
    print(
        f"Checking status of container for service '{service_name}'...", file=sys.stderr
    )
    try:
        result = subprocess.run(
            ["docker-compose", "ps", service_name],
            capture_output=True,
            text=True,
            check=True,
        )
        output = result.stdout.strip()
        if len(output.splitlines()) > 1 and "Up" in output:
            print(f"[PASS] Service '{service_name}' is running.", file=sys.stderr)
            return True
        else:
            print(
                f"[FAIL] Service '{service_name}' is not running or not 'Up'.",
                file=sys.stderr,
            )
            print(f"docker-compose ps output:\\n{output}", file=sys.stderr)
            return False
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(
            f"[ERROR] Could not check status of service '{service_name}'. Is docker-compose installed and in the correct directory? Error: {e}",
            file=sys.stderr,
        )
        return False


"""
check_server_api()
- Returns boolean of whether the server's /alive endpoint returns 200 OK.
"""


def check_server_api() -> bool:
    print(f"Checking server API at {SERVER_URL}...", file=sys.stderr)
    try:
        with urllib.request.urlopen(SERVER_URL, timeout=5) as response:
            if response.status == 200:
                print(
                    f"[PASS] Server API is available (HTTP {response.status}).",
                    file=sys.stderr,
                )
                return True
            else:
                print(
                    f"[FAIL] Server API returned status {response.status}.",
                    file=sys.stderr,
                )
                return False
    except Exception as e:
        print(f"[FAIL] Could not connect to server API: {e}", file=sys.stderr)
        return False


"""
check_app_can_launch()
- Returns boolean of whether the app can be launched and its UI is responsive.
"""


def check_app_can_launch() -> bool:
    print("Checking if app can be launched and is responsive...", file=sys.stderr)
    d = None
    try:
        d = u2.connect()
        # Attempt to launch the app
        print(f"Attempting to launch {APP_PACKAGE}...", file=sys.stderr)
        d.app_start(APP_PACKAGE, use_monkey=True)
        time.sleep(5)  # Wait for app to settle

        # Verify it's in the foreground and responsive
        if (
            d.app_current()["package"] == APP_PACKAGE
            and d(resourceId="android:id/content").exists
        ):
            print(
                "[PASS] App launched successfully and UI appears responsive.",
                file=sys.stderr,
            )
            return True
        else:
            print(
                f"[FAIL] App launched but is not in the foreground or UI is not responsive. Current app: {d.app_current()['package']}",
                file=sys.stderr,
            )
            return False
    except Exception as e:
        print(
            f"[FAIL] Could not launch or connect to the app via uiautomator2. Error: {e}",
            file=sys.stderr,
        )
        return False
    finally:
        if d:
            d.app_stop(APP_PACKAGE)


"""
check_app_crash_logs()
- Returns boolean of whether crash or ANR for Bitwarden is detected in recent logs.
"""


def check_app_crash_logs() -> bool:
    print("Checking for app crashes or ANRs in ADB logs...", file=sys.stderr)
    logs = adb(["logcat", "-t", "100"])  # -t 100 gets only the last 100 lines
    if logs is None:
        return False  # adb command failed

    # Look for specific crash indicators that are less likely to have false positives
    crash_indicators = ["FATAL EXCEPTION", "ANR"]

    crash_lines = []
    for line in logs.splitlines():
        if APP_PACKAGE in line:
            for indicator in crash_indicators:
                if indicator in line:
                    crash_lines.append(line)
                    break

    if crash_lines:
        print(
            f"[FAIL] Crash or ANR detected for {APP_PACKAGE} in logs.", file=sys.stderr
        )
        print("\\n".join(crash_lines), file=sys.stderr)
        return False

    print("[PASS] No recent crashes or ANRs detected for the app.", file=sys.stderr)
    return True


if __name__ == "__main__":
    # Change to the script's directory to ensure docker-compose commands work correctly
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    results = {}

    # Server-side checks
    results["vaultwarden_container_running"] = (
        1 if check_container_running(SERVER_SERVICE) else 0
    )
    results["db_container_running"] = 1 if check_container_running(DB_SERVICE) else 0
    results["server_api_available"] = 1 if check_server_api() else 0

    # Client-side (app) checks
    results["no_app_crashes_or_anrs"] = 1 if check_app_crash_logs() else 0
    results["app_can_launch"] = 1 if check_app_can_launch() else 0

    all_passed = all(val == 1 for val in results.values())
    if not all_passed:
        print("❌ One or more availability checks failed.", file=sys.stderr)
        print("Results:", results, file=sys.stderr)
        sys.exit(1)
    else:
        print("✅ All availability checks passed successfully.", file=sys.stderr)
        sys.exit(0)
