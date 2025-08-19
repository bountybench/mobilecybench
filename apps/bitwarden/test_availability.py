"""
test_availability.py checks if the Bitwarden app and its server are running and responsive.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

from utils.ui_utils import initialize_ui_automation

from .util import BITWARDEN_PKG, adb

SERVER_SERVICE = "vaultwarden"
DB_SERVICE = "db"
SERVER_URL = "http://localhost:8000/alive"

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
        print(f"Attempting to launch {BITWARDEN_PKG}...", file=sys.stderr)
        d.app_start(BITWARDEN_PKG, use_monkey=True)
        time.sleep(8)

        if d(resourceId="AlertPopup").exists:
            print("Error dialog detected. Dismissing...", file=sys.stderr)
            d(resourceId="AcceptAlertButton").click()
            time.sleep(2)

        current_app = d.app_current()["package"]
        if current_app == BITWARDEN_PKG:
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
            d.app_stop(BITWARDEN_PKG)


def check_app_crash_logs() -> bool:
    """Checks for crash or ANR indicators in recent ADB logs."""
    print(
        f"[INFO]Checking for {BITWARDEN_PKG} crashes or ANRs in ADB logs...",
        file=sys.stderr,
    )
    logs = adb(["logcat", "-t", "500"])
    if logs is None:
        print("[ERROR] No ADB logs found.", file=sys.stderr)
        return False

    # 1) Detect classic Android crash pattern: FATAL EXCEPTION + matching Process line
    lines = logs.splitlines()
    for i, line in enumerate(lines):
        if "FATAL EXCEPTION" in line:
            for nearby_line in lines[i - 3 : i + 3]:
                if f"Process: {BITWARDEN_PKG}" in nearby_line:
                    print(
                        f"[FAIL] Crash detected for {BITWARDEN_PKG}: FATAL EXCEPTION with matching process.",
                        file=sys.stderr,
                    )
                    return False

    # 2) Detect inline indicators that include the package on the same line
    inline_indicators = [
        "ANR in",
        "has died",
        "WIN DEATH",
        "Force finishing activity",
        "crash",
    ]
    inline_hits = [
        line
        for line in logs.splitlines()
        if (BITWARDEN_PKG in line) and any(ind in line for ind in inline_indicators)
    ]

    if inline_hits:
        print(
            f"[FAIL] Crash/ANR indicators found for {BITWARDEN_PKG}.", file=sys.stderr
        )
        print("\\n".join(inline_hits), file=sys.stderr)
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
