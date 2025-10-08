import json
import sys

from utils.confidentiality_utils import check_leak_indicators


# Invoke individually with `python3 evaluation/generic_probes/test_confidentiality.py home-assistant-android`
# Exits with code 0 if all tests pass, 1 if any test fails
def main():
    results_summary = {}
    results_summary["score"] = 0

    log_path = sys.argv[1]
    with open(log_path, "r") as f:
        log = f.read()

    if not check_leak_indicators(log):
        print("Some tests failed.", file=sys.stderr)
        results_summary["score"] = 0
    else:
        print("All tests passed successfully.", file=sys.stderr)
        results_summary["score"] = 1
    print(json.dumps(results_summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
