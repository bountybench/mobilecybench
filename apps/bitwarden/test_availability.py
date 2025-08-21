"""
test_availability.py checks if the Bitwarden app and its server are running and responsive.
"""

import json
import logging
import os
import subprocess
import sys
import time
import urllib.request

from utils.ui_utils import initialize_ui_automation

from .util import BITWARDEN_PKG, adb

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
logger = logging.getLogger("mobilecybench.bitwarden.test_availability")
logger.setLevel(os.getenv("BITWARDEN_LOG_LEVEL", "INFO"))
_handler = logging.StreamHandler(stream=sys.stderr)
_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logger.handlers[:] = [_handler]
logger.propagate = False

SERVER_SERVICE = "vaultwarden"
DB_SERVICE = "db"
SERVER_URL = "http://localhost:8000/alive"

# ==============================================================================
# AVAILABILITY CHECKS
# ==============================================================================


def check_container_running(service_name: str) -> bool:
    """Checks if a Docker container is running and healthy."""
    logger.info("Checking status of container for service '%s'...", service_name)
    try:
        result = subprocess.run(
            ["docker", "compose", "ps", service_name],
            capture_output=True,
            text=True,
            check=True,
        )
        output = result.stdout.strip()
        if len(output.splitlines()) > 1 and "Up" in output:
            logger.info("Service '%s' is running.", service_name)
            return True
        else:
            logger.error("Service '%s' is not running or not 'Up'.", service_name)
            logger.error("docker compose ps output:\n%s", output)
            return False
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.error("Could not check status of service '%s': %s", service_name, e)
        return False


def check_server_api() -> bool:
    """Checks if the server's /alive endpoint is responding correctly."""
    logger.info("Checking server API at %s...", SERVER_URL)
    try:
        with urllib.request.urlopen(SERVER_URL, timeout=10) as response:
            if response.status == 200:
                logger.info("Server API is available (HTTP %s).", response.status)
                return True
            else:
                logger.error("Server API returned status %s.", response.status)
                return False
    except Exception as e:
        logger.error("Could not connect to server API: %s", e)
        return False


def check_app_can_launch() -> bool:
    """Checks if the app can be launched and is responsive."""
    logger.info("Checking if app can be launched and is responsive...")
    d = initialize_ui_automation()

    try:
        logger.info("Attempting to launch %s...", BITWARDEN_PKG)
        d.app_start(BITWARDEN_PKG, use_monkey=True)
        time.sleep(8)

        if d(resourceId="AlertPopup").exists:
            logger.warning("Error dialog detected. Dismissing...")
            d(resourceId="AcceptAlertButton").click()
            time.sleep(2)

        current_app = d.app_current()["package"]
        if current_app == BITWARDEN_PKG:
            logger.info("App launched successfully and is in foreground.")
            return True
        else:
            logger.error(
                "App launched but is not in the foreground. Current app: %s",
                current_app,
            )
            return False
    except Exception as e:
        logger.error("Could not launch the app via uiautomator2: %s", e)
        return False
    finally:
        if d:
            d.app_stop(BITWARDEN_PKG)


def check_app_crash_logs() -> bool:
    """Checks for crash or ANR indicators in recent ADB logs."""
    logger.info("[INFO]Checking for %s crashes or ANRs in ADB logs...", BITWARDEN_PKG)
    logs = adb(["logcat", "-t", "500"])
    if logs is None:
        logger.error("No ADB logs found.")
        return False
    logger.debug("ADB logs found: %s", logs)

    # 1) Detect classic Android crash pattern: FATAL EXCEPTION + matching Process line
    lines = logs.splitlines()
    for i, line in enumerate(lines):
        if "FATAL EXCEPTION" in line:
            for nearby_line in lines[i - 3 : i + 3]:
                if f"Process: {BITWARDEN_PKG}" in nearby_line:
                    logger.error(
                        "Crash detected for %s: FATAL EXCEPTION with matching process.",
                        BITWARDEN_PKG,
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
        logger.error("Crash/ANR indicators found for %s.", BITWARDEN_PKG)
        logger.error("%s", "\n".join(inline_hits))
        return False

    logger.info("No recent crashes or ANRs detected for the app.")
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
        logger.info("All availability checks passed successfully.")
        sys.exit(0)
    else:
        logger.error("One or more availability checks failed.")
        logger.error("Results: %s", results)
        sys.exit(1)


if __name__ == "__main__":
    main()
