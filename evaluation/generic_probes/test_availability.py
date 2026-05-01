import json
import sys

from applicability import apply_applicability, load_category_applicability
from helpers import get_metadata

from utils.availability_utils import check_container_health


# Exits with code 0 if tests successfully execute, other exit codes indicate unexpected probe failure
def main():
    metadata = get_metadata()
    applicability = load_category_applicability("availability")

    container_names = metadata.get("container_names", [])

    results_summary = {}

    if applicability.get("check_container_health", False):
        results_summary["check_container_health"] = (
            1 if all(check_container_health(name) for name in container_names) else 0
        )

    results_summary = apply_applicability(results_summary, applicability)
    if not results_summary["score"]:
        print("Some tests failed.", file=sys.stderr)
    else:
        print("All tests passed successfully.", file=sys.stderr)
    print(json.dumps(results_summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
