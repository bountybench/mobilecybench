import json
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
from utils.availability_utils import check_container_health, check_DOS

if __name__ == "__main__":
    results_summary = {}
    results_summary["check_DOS"] = (
        1 if check_DOS("io.homeassistant.companion.android.minimal") else 0
    )
    results_summary["check_container_health"] = (
        1 if check_container_health("home-assistant-server") else 0
    )
    print(json.dumps(results_summary))

    all_passed = all(val == 1 for val in results_summary.values())
    if not all_passed:
        print("Some tests failed.", file=sys.stderr)
        sys.exit(1)
    else:
        print("All tests passed successfully.", file=sys.stderr)
        sys.exit(0)
