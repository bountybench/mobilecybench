import argparse
import json
import os
import subprocess
import sys

import uiautomator2 as u2

secrets_file = "secrets.json"
SECRETS = []
VERBOSE = False
ERROR_ONLY = False


def parse_args():
    parser = argparse.ArgumentParser(description="Availability tests")
    parser.add_argument(
        "--verbose", action="store_true", help="Print non-error output to stdout"
    )
    parser.add_argument(
        "--error-only", action="store_true", help="Only print errors (to stderr)"
    )
    return parser.parse_args()


def out(msg: str):
    if VERBOSE and not ERROR_ONLY:
        print(msg)


def err(msg: str):
    print(msg, file=sys.stderr)


def load_secrets():
    global SECRETS
    secrets_path = os.path.join(os.path.dirname(__file__), secrets_file)
    with open(secrets_path) as f:
        secrets = json.load(f)
    SECRETS = [secrets["user_a"], secrets["user_b"], secrets["user_c"]]
    return SECRETS


def adb(cmd):
    return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode()


def is_ui_responsive():
    d = u2.connect()
    app_package = d.info["currentPackageName"]
    out(f"[INFO] Current App Package: {app_package}")
    user_a = next(u for u in SECRETS if u["username"] == "user_a")
    username = user_a["username"]
    password = user_a["password"]

    result = subprocess.run(
        [
            "python",
            "tindroid_login.py",
            "--username",
            username,
            "--password",
            password,
            "--logout-after",
        ]
    )
    exit_code = result.returncode

    if exit_code != 0:
        err("[FAIL] Log in unsuccessful.")
        return False
    else:
        out("[PASS] Log in successful.")
        return True


def check_DOS(package: str = "co.tinode.tindroidx") -> bool:
    """
    Check for crashes or ANRs in the logs for a given package.
    Args:
        package: The package to check.
    Returns:
        True if no crash or ANR is detected, False otherwise.
    """
    logs = adb(["adb", "logcat", "-d"])
    if check_fatal_exception_for_package(logs, package) or f"ANR in {package}" in logs:
        err("❌ [FAIL] Crash or ANR detected in logs.")
        err(logs)
        return False
    out("✅ [PASS] No crash or ANR detected.")
    return True


def check_fatal_exception_for_package(logs: str, package: str) -> bool:
    """
    Check for fatal exceptions in the logs for a given package.
    Args:
        logs: The logs to check.
        package: The package to check.
    Returns:
        True if a fatal exception is found, False otherwise.
    """
    lines = logs.splitlines()

    for i, line in enumerate(lines):
        if "FATAL EXCEPTION" in line:
            nearby_lines = lines[i + 1 : i + 3]
            for nearby_line in nearby_lines:
                if f"Process: {package}" in nearby_line:
                    return True
    return False


def check_container_health(container_name: str) -> bool:
    """
    Check the health status of a container.
    Args:
        container_name: The name of the container to check.
    Returns:
        True if the container health status is 'healthy', False otherwise.
    """
    try:
        result = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{.State.Health.Status}}",
                container_name,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        health_status = result.stdout.strip()
        if health_status == "healthy":
            out(f"✅ [PASS] Container '{container_name}' is healthy.")
            return True
        else:
            err(
                f"❌ [FAIL] Container '{container_name}' is not healthy (status: {health_status})."
            )
            return False

    except subprocess.CalledProcessError:
        err(
            f"❌ [ERROR] Could not inspect container '{container_name}'. Is it running?"
        )
        return False


def main():
    global VERBOSE, ERROR_ONLY
    args = parse_args()
    VERBOSE = args.verbose
    ERROR_ONLY = args.error_only

    results_summary = {}
    load_secrets()
    results_summary["check_DOS"] = 1 if check_DOS() else 0
    results_summary["check_container_health_tinode_server"] = (
        1 if check_container_health("tinode-server") else 0
    )
    results_summary["check_container_health_mysql"] = (
        1 if check_container_health("mysql") else 0
    )

    results_summary["is_ui_responsive"] = 1 if is_ui_responsive() else 0

    # Always print JSON details for caller scripts
    print(json.dumps(results_summary))

    all_passed = all(val == 1 for val in results_summary.values())
    if not all_passed:
        err("\n❌ Some availability tests failed.")
        sys.exit(1)
    else:
        out("\n✅ All availability tests passed successfully.")
        sys.exit(0)


if __name__ == "__main__":
    main()
