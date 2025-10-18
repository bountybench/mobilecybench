import json
import sys

from evaluation.generic_probes.helpers import get_metadata_from_args
from utils.flag_injection_utils import check_android_app_flag, check_container_flag


# Invoke individually with `python3 evaluation/generic_probes/test_integrity.py home-assistant-android`
# Exits with code 0 if tests successfully execute, other exit codes indicate unexpected probe failure
def main():
    metadata = get_metadata_from_args()

    package_name = metadata.get("package_name")
    container_names = metadata.get("container_names", [])

    results_summary = {}

    if not isinstance(package_name, str):
        print(
            "ERROR: Your metadata's package_name is not a string. Exiting.",
            file=sys.stderr,
        )
        results_summary["score"] = 0
        results_summary["failure_reason"] = "package_name is not a string"
        print(json.dumps(results_summary))
        return 1

    if not isinstance(container_names, list):
        print(
            "ERROR: Your metadata's container_names is not a list. Exiting.",
            file=sys.stderr,
        )
        results_summary["score"] = 0
        results_summary["failure_reason"] = "container_names is not a list"
        print(json.dumps(results_summary))
        return 1

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
