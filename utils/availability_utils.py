import re
import subprocess
import sys


def adb(cmd):
    return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode()


def check_DOS(package_name: str) -> bool:
    """Return True if no crash or ANR detected, False otherwise."""
    """Takes in the package name, i.e. net.cozic.joplin"""
    logs = adb(["adb", "logcat", "-d"])
    if check_fatal_exception(logs, package_name) or f"ANR in {package_name}" in logs:
        print(
            f"[FAIL] Crash or ANR detected in logs for {package_name}.", file=sys.stderr
        )
        return False
    print(f"[PASS] No crash or ANR detected for {package_name}.", file=sys.stderr)
    return True


def check_DOS_comprehensive(package_name: str) -> bool:
    """Return True if no crash detected, False if crash detected.

    This is a more robust version that uses multiple detection methods
    and better timing to avoid false negatives in CI environments.
    """

    # Method 1: Check recent logs for crash indicators
    result = subprocess.run(
        ["adb", "shell", "logcat", "-d", "-t", "1000"],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode == 0:
        logs = result.stdout

        # Look for the same crash indicators as the original check_DOS
        crash_indicators = [
            f"FATAL EXCEPTION.*{package_name}",
            f"AndroidRuntime.*{package_name}",
            f"Process {package_name}.*has died",
            f"Activity.*{package_name}.*crashed",
            f"Application.*{package_name}.*crashed",
            f"ANR in {package_name}",
        ]

        for pattern in crash_indicators:
            if re.search(pattern, logs, re.IGNORECASE):
                print(
                    f"[FAIL] Crash detected in {package_name}: {pattern}",
                    file=sys.stderr,
                )
                return False

    # Method 2: Check for crash events in system dropbox
    dropbox_result = subprocess.run(
        ["adb", "shell", "dumpsys", "dropbox", "|", "grep", "-i", "crash"],
        capture_output=True,
        text=True,
        check=False,
        shell=True,
    )

    if dropbox_result.stdout.strip() and package_name in dropbox_result.stdout:
        print(
            f"[FAIL] Crash event found in dropbox for {package_name}", file=sys.stderr
        )
        return False

    # Method 3: Check for ANR events in system dropbox
    anr_result = subprocess.run(
        ["adb", "shell", "dumpsys", "dropbox", "|", "grep", "-i", "anr"],
        capture_output=True,
        text=True,
        check=False,
        shell=True,
    )

    if anr_result.stdout.strip() and package_name in anr_result.stdout:
        print(f"[FAIL] ANR event found in dropbox for {package_name}", file=sys.stderr)
        return False

    print(f"[PASS] No crash or ANR detected for {package_name}", file=sys.stderr)
    return True


def check_fatal_exception(logs: str, package_name: str) -> bool:
    lines = logs.splitlines()
    for i, line in enumerate(lines):
        if "FATAL EXCEPTION" in line:
            nearby_lines = lines[i + 1 : i + 3]
            for nearby_line in nearby_lines:
                if f"Process: {package_name}" in nearby_line:
                    return True
    return False


def check_container_health(container_name: str) -> bool:
    """Return True if the container health status is 'healthy', False otherwise."""
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
            print(f"[PASS] Container '{container_name}' is healthy.", file=sys.stderr)
            return True
        else:
            print(
                f"[FAIL] Container '{container_name}' is not healthy (status: {health_status}).",
                file=sys.stderr,
            )
            return False

    except subprocess.CalledProcessError:
        print(
            f"[ERROR] Could not inspect container '{container_name}'. Is it running?",
            file=sys.stderr,
        )
        return False
