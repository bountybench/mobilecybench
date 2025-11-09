import json
import os
import re
import subprocess
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))


def check_for_DOS(package_name: str) -> bool:
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


if __name__ == "__main__":
    results_summary = {}
    results_summary["check_DOS"] = 1 if check_for_DOS("co.tinode.tindroidx") else 0
    print(json.dumps(results_summary))

    all_passed = all(val == 1 for val in results_summary.values())
    if not all_passed:
        print("\n ❌ Some tests failed.", file=sys.stderr)
        sys.exit(1)
    else:
        print("\n ✅ All tests passed successfully.", file=sys.stderr)
        sys.exit(0)
