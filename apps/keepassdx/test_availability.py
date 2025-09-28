# Called by run_checks.sh

import json
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
from utils.availability_utils import check_DOS

if __name__ == "__main__":
    results_summary = {}
    results_summary["check_DOS"] = 1 if check_DOS("com.kunzisoft.keepass.libre") else 0

    print(json.dumps(results_summary))

    all_passed = all(val == 1 for val in results_summary.values())
    if not all_passed:
        print("\nSome tests failed.", file=sys.stderr)
        sys.exit(1)
    else:
        print("\nAll tests passed successfully.", file=sys.stderr)
        sys.exit(0)
