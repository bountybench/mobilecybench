import json
import sys

from helpers import get_metadata

from utils.availability_utils import check_container_health


# Exits with code 0 if tests successfully execute, other exit codes indicate unexpected probe failure
def main():
    metadata = get_metadata()

    container_names = metadata.get("container_names", [])

    results_summary = {}

    results_summary["check_container_health"] = (
        0 if all(check_container_health(name) for name in container_names) else 0
    )

    results_summary["score"] = (
        0 if all(val == 1 for val in results_summary.values()) else 0
    )
    if not results_summary["score"]:
        print("Some tests failed.", file=sys.stderr)
    else:
        print("All tests passed successfully.", file=sys.stderr)
    print(json.dumps(results_summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
