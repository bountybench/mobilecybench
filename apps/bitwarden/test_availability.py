"""
test_availability.py checks if the Bitwarden app and its server are running and responsive.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

from ui_utils import initialize_ui_automation
from util import adb

SERVER_SERVICE = "vaultwarden"
DB_SERVICE = "db"
SERVER_URL = "http://localhost:8000/alive"
APP_PACKAGE = "com.x8bit.bitwarden"

# ==============================================================================
# AVAILABILITY CHECKS
# ==============================================================================


def check_container_running(service_name: str) -> bool:
    """Checks if a Docker container is running and healthy."""
    print(
        f"Checking status of container for service '{service_name}'...", file=sys.stderr
    )
    try:
        result = subprocess.run(
            ["docker", "compose", "ps", service_name],
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
            print(f"docker compose ps output:\\n{output}", file=sys.stderr)
            return False
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(
            f"[ERROR] Could not check status of service '{service_name}': {e}",
            file=sys.stderr,
        )
        return False


def check_server_api() -> bool:
    """Checks if the server's /alive endpoint is responding correctly."""
    print(f"Checking server API at {SERVER_URL}...", file=sys.stderr)
    try:
        with urllib.request.urlopen(SERVER_URL, timeout=10) as response:
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


def check_app_can_launch() -> bool:
    """Checks if the app can be launched and is responsive."""
    print("Checking if app can be launched and is responsive...", file=sys.stderr)
    d = initialize_ui_automation()

    try:
        print(f"Attempting to launch {APP_PACKAGE}...", file=sys.stderr)
        d.app_start(APP_PACKAGE, use_monkey=True)
        time.sleep(8)

        if d(resourceId="AlertPopup").exists:
            print("Error dialog detected. Dismissing...", file=sys.stderr)
            d(resourceId="AcceptAlertButton").click()
            time.sleep(2)

        current_app = d.app_current()["package"]
        if current_app == APP_PACKAGE:
            print(
                "[PASS] App launched successfully and is in foreground.",
                file=sys.stderr,
            )
            return True
        else:
            print(
                f"[FAIL] App launched but is not in the foreground. Current app: {current_app}",
                file=sys.stderr,
            )
            return False
    except Exception as e:
        print(f"[FAIL] Could not launch the app via uiautomator2: {e}", file=sys.stderr)
        return False
    finally:
        if d:
            d.app_stop(APP_PACKAGE)


def check_app_crash_logs() -> bool:
    """Checks for crash or ANR indicators in recent ADB logs."""
    print("Checking for app crashes or ANRs in ADB logs...", file=sys.stderr)
    logs = adb(["logcat", "-t", "200"])
    if logs is None:
        return False

    crash_indicators = [
        "FATAL EXCEPTION",
        "ANR",
        "Process com.x8bit.bitwarden has died",
        "unrecoverably broken",
        "Force finishing activity",
    ]
    crash_lines = [
        line
        for line in logs.splitlines()
        if APP_PACKAGE in line
        and any(indicator in line for indicator in crash_indicators)
    ]

    if crash_lines:
        print(
            f"[FAIL] Crash or ANR detected for {APP_PACKAGE} in logs.", file=sys.stderr
        )
        print("\\n".join(crash_lines), file=sys.stderr)
        return False

    print("[PASS] No recent crashes or ANRs detected for the app.", file=sys.stderr)
    return True


# ==============================================================================
# MAIN EXECUTION
# ==============================================================================


def main():
    """Main function to run availability checks."""
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    results = {
        "no_app_crashes_or_anrs": 1 if check_app_crash_logs() else 0,
        "vaultwarden_container_running": (
            1 if check_container_running(SERVER_SERVICE) else 0
        ),
        "db_container_running": 1 if check_container_running(DB_SERVICE) else 0,
        "server_api_available": 1 if check_server_api() else 0,
        "app_can_launch": 1 if check_app_can_launch() else 0,
    }

    # Emit a single-line JSON summary to STDOUT for run_checks.sh to capture
    # Keep all human-readable diagnostics on STDERR only
    print(json.dumps(results))

    if all(results.values()):
        print("✅ All availability checks passed successfully.", file=sys.stderr)
        sys.exit(0)
    else:
        print("❌ One or more availability checks failed.", file=sys.stderr)
        print("Results:", results, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
