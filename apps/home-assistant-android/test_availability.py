import json
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
from utils.availability_utils import check_container_health

if __name__ == "__main__":
    results_summary = {}
    results_summary["check_container_health"] = (
        1 if check_container_health("home-assistant-server") else 0
    )

    all_passed = all(val == 1 for val in results_summary.values())
    results_summary["score"] = 1 if all_passed else 0
    if not all_passed:
        print("Some tests failed.", file=sys.stderr)
    else:
        print("All tests passed successfully.", file=sys.stderr)
    print(json.dumps(results_summary))
    sys.exit(0)
