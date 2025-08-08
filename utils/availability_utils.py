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
        return health_status == "healthy"
    except subprocess.CalledProcessError:
        print(
            f"Error: Could not inspect container '{container_name}'. Is it running?",
            file=sys.stderr,
        )
        return False
