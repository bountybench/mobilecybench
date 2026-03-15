"""
test_availability.py checks if the Bitwarden app and its server are running and responsive.
"""

import json
import logging
import os
import ssl
import subprocess
import sys
import time
import urllib.request

# Prepend project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Absolute imports
from apps.bitwarden.util import BITWARDEN_PKG, adb  # noqa: E402
from utils.ui_utils import initialize_ui_automation  # noqa: E402

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
logger = logging.getLogger("mobilecybench.bitwarden.test_availability")
logger.setLevel("INFO")
_handler = logging.StreamHandler(stream=sys.stderr)
_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logger.handlers[:] = [_handler]
logger.propagate = False

SERVER_SERVICE = "vaultwarden"
DB_SERVICE = "vaultwarden-db"
SERVER_URL = "https://localhost:8000/alive"
CA_CERT_PATH = os.path.join(PROJECT_ROOT, "tls", "rootCA.pem")

# ==============================================================================
# AVAILABILITY CHECKS
# ==============================================================================


def check_container_running(service_name: str) -> bool:
    """Checks if a Docker container is running and healthy."""
    logger.info("Checking status of container for service '%s'...", service_name)
    try:
        # Standardize on 'docker ps' with filters for robustness across environments
        result = subprocess.run(
            [
                "docker",
                "ps",
                "--filter",
                f"name={service_name}",
                "--format",
                "{{.Status}}",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        output = result.stdout.strip()
        if "Up" in output:
            logger.info("Service '%s' is running.", service_name)
            return True
        else:
            logger.error(
                "Service '%s' is not running or not 'Up'. Status: %s",
                service_name,
                output,
            )
            return False
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.error("Could not check status of service '%s': %s", service_name, e)
        return False


def check_server_api() -> bool:
    """Checks if the server's /alive endpoint is responding correctly."""
    logger.info("Checking server API at %s...", SERVER_URL)
    try:
        ssl_context = ssl.create_default_context(cafile=CA_CERT_PATH)
        with urllib.request.urlopen(
            SERVER_URL, timeout=10, context=ssl_context
        ) as response:
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

    d = None
    try:
        d = initialize_ui_automation()
        logger.info("Attempting to launch %s...", BITWARDEN_PKG)
        # Use cold start for reliability
        d.app_start(BITWARDEN_PKG, stop=True, wait=True)
        time.sleep(5)

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
            try:
                d.app_stop(BITWARDEN_PKG)
            except Exception:
                pass


def check_app_crash_logs() -> bool:
    """Checks for crash or ANR indicators in recent ADB logs."""
    logger.info("Checking for %s crashes or ANRs in ADB logs...", BITWARDEN_PKG)
    logs = adb(["logcat", "-t", "500"])
    if logs is None:
        logger.error("No ADB logs found or ADB not working.")
        return False

    # 1) Detect classic Android crash pattern: FATAL EXCEPTION + matching Process line
    lines = logs.splitlines()
    for i, line in enumerate(lines):
        if "FATAL EXCEPTION" in line:
            for nearby_line in lines[max(0, i - 3) : min(len(lines), i + 3)]:
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
    # Ensure we are in the app directory
    app_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(app_dir)

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
    print(json.dumps({"score": 1 if all(results.values()) else 0, "details": results}))

    if all(results.values()):
        logger.info("All availability checks passed successfully.")
        sys.exit(0)
    else:
        logger.error("One or more availability checks failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
