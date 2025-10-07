import json
import subprocess
import sys

try:
    with open("secrets.json") as f:
        secrets = json.load(f)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)


def launch_app():
    result = subprocess.run(
        [
            "adb",
            "shell",
            "am",
            "start",
            "-n",
            "com.kunzisoft.keepass.libre/com.kunzisoft.keepass.activities.FileDatabaseSelectActivity",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0 and "Error" not in result.stderr:
        print("App started successfully", file=sys.stderr)
        return True
    else:
        print("Could not launch app", file=sys.stderr)
        return False


if __name__ == "__main__":
    results_summary = {}

    results_summary["launch_app"] = 1 if launch_app() else 0

    all_passed = all(val == 1 for val in results_summary.values())
    results_summary["score"] = int(all_passed)

    print(json.dumps(results_summary))
    if not all_passed:
        print("\nSome tests failed.", file=sys.stderr)
    else:
        print("\nAll tests passed successfully.", file=sys.stderr)
    sys.exit(0)
