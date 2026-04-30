import json
import sys

from helpers import (
    compute_generic_probe_score,
    get_metadata,
    is_generic_probe_applicable,
)

from utils.availability_utils import check_container_health


# Exits with code 0 if tests successfully execute, other exit codes indicate unexpected probe failure
def main():
    metadata = get_metadata()

    container_names = metadata.get("container_names", [])

    results_summary = {}

    if is_generic_probe_applicable("availability.check_container_health"):
        results_summary["check_container_health"] = (
            1 if all(check_container_health(name) for name in container_names) else 0
        )
    else:
        results_summary["check_container_health"] = None

    results_summary["score"] = compute_generic_probe_score(results_summary)
    if results_summary["score"] == 0:
        print("Some tests failed.", file=sys.stderr)
    elif results_summary["score"] == 1:
        print("All tests passed successfully.", file=sys.stderr)
    else:
        print("No applicable generic availability probes.", file=sys.stderr)
    print(json.dumps(results_summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
