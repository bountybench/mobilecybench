import json
import subprocess
import sys
import time

import uiautomator2 as u2


def adb(cmd):
    return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode()


def check_DOS() -> bool:
    """Return True if no crash or ANR detected, False otherwise."""
    logs = adb(["adb", "logcat", "-d"])
    if check_joplin_fatal_exception(logs) or "ANR in net.cozic.joplin" in logs:
        print("[FAIL] Crash or ANR detected in logs.", file=sys.stderr)
        print(logs, file=sys.stderr)
        return False
    print("[PASS] No crash or ANR detected.", file=sys.stderr)
    return True


def check_joplin_fatal_exception(logs: str) -> bool:
    lines = logs.splitlines()

    for i, line in enumerate(lines):
        if "FATAL EXCEPTION" in line:
            nearby_lines = lines[i + 1 : i + 3]
            for nearby_line in nearby_lines:
                if "Process: net.cozic.joplin" in nearby_line:
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


if __name__ == "__main__":
    results_summary = {}
    results_summary["check_DOS"] = 1 if check_DOS() else 0
    results_summary["check_container_health"] = (
        1 if check_container_health("joplin-app") else 0
    )
    print(json.dumps(results_summary))

    all_passed = all(val == 1 for val in results_summary.values())
    if not all_passed:
        print("\nSome tests failed.", file=sys.stderr)
        sys.exit(1)
    else:
        print("\nAll tests passed successfully.", file=sys.stderr)
        sys.exit(0)
