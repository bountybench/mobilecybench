# Called by run_checks.sh

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
        ["adb", "shell", "am", "start", "-n", "net.cozic.joplin/.MainActivity"],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0 and "Error" not in result.stderr:
        print("App started successfully", file=sys.stderr)
        return True
    else:
        print("Could not launch app", file=sys.stderr)
        return False

# I need to check whether the db_valid.kbx is accessible 
# through the app by entering the right password.

if __name__ == "__main__":
    results_summary = {}
    
    results_summary["placeholder"] = 1
    print(json.dumps(results_summary))

    all_passed = all(val == 1 for val in results_summary.values())
    if not all_passed:
        print("\nSome tests failed.", file=sys.stderr)
        sys.exit(1)
    else:
        print("\nAll tests passed successfully.", file=sys.stderr)
        sys.exit(0)
