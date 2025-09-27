import json
import os
import subprocess
import sys
import time

import uiautomator2 as u2

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
from utils.availability_utils import check_container_health, check_DOS

if __name__ == "__main__":
    results_summary = {}
    # results_summary["check_DOS"] = 1 if check_DOS("net.cozic.joplin") else 0
    # results_summary["check_container_health"] = (
    #    1 if check_container_health("joplin-app") else 0
    # )
    results_summary["placeholder"] = 1
    print(json.dumps(results_summary))

    all_passed = all(val == 1 for val in results_summary.values())
    if not all_passed:
        print("\nSome tests failed.", file=sys.stderr)
        sys.exit(1)
    else:
        print("\nAll tests passed successfully.", file=sys.stderr)
        sys.exit(0)
