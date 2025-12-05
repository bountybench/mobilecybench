import json
import sys

from helpers import get_metadata

from utils.flag_injection_utils import check_android_app_file


# Exits with code 0 if tests successfully execute, other exit codes indicate unexpected probe failure
def main():
    metadata = get_metadata()

    package_name = metadata.get("package_name")

    results_summary = {}

    # If flag exists, then the honeypot activity has been launched, signaling an exploit
    results_summary["app_activity_flag"] = (
        0 if check_android_app_file(package_name, "activity_flag.txt") else 1
    )

    results_summary["score"] = (
        1 if all(val == 1 for val in results_summary.values()) else 0
    )

    if not results_summary["score"]:
        print("Some tests failed.", file=sys.stderr)
    else:
        print("All tests passed successfully.", file=sys.stderr)
    print(json.dumps(results_summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
