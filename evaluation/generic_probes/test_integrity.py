import json
import sys

from helpers import get_metadata
from utils.flag_injection_utils import check_android_app_flag, check_container_flag


# Exits with code 0 if tests successfully execute, other exit codes indicate unexpected probe failure
def main():
    metadata = get_metadata()

    package_name = metadata.get("package_name")
    container_names = metadata.get("container_names", [])

    results_summary = {}

    results_summary["app_flag"] = 1 if check_android_app_flag(package_name) else 0
    results_summary["container_flag"] = (
        1
        if all(
            check_container_flag(container_name) for container_name in container_names
        )
        else 0
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
