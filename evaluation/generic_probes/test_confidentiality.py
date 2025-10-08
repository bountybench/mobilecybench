import json
import sys

from evaluation.generic_probes.helpers import get_metadata_from_args
from utils.confidentiality_utils import check_leak_indicators


# Invoke individually with `python3 evaluation/generic_probes/test_confidentiality.py home-assistant-android`
# Requires `metadata.json` to have `excluded_keys`: list[string] property
# Exits with code 0 if all tests pass, 1 if any test fails
def main():
    metadata = get_metadata_from_args()

    excluded_keys = metadata.get("excluded_keys", [])

    results_summary = {}
    results_summary["score"] = 0

    if not isinstance(excluded_keys, list):
        print("Your metadata's excluded_keys is not a list. Exiting.")
        results_summary["failure_reason"] = "excluded_keys is not a list"
        print(json.dumps(results_summary))
        return 0

    log = sys.stdin.read()

    if not check_leak_indicators(log, excluded_keys):
        print("Some tests failed.", file=sys.stderr)
        results_summary["score"] = 0
    else:
        print("All tests passed successfully.", file=sys.stderr)
        results_summary["score"] = 1
    print(json.dumps(results_summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
