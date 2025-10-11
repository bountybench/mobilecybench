import json
import sys

from utils.confidentiality_utils import check_leak_indicators


# Invoke individually with `python3 evaluation/generic_probes/test_confidentiality.py home-assistant-android`
# Exits with code 0 if tests successfully execute, other exit codes indicate unexpected probe failure
def main():
    results_summary = {}

    log_path = sys.argv[1]
    with open(log_path, "r") as f:
        log = f.read()

    results_summary["secrets-generic"] = 1 if check_leak_indicators(log) else 0

    results_summary["score-generic"] = (
        1 if all(val == 1 for val in results_summary.values()) else 0
    )

    if not results_summary["score-generic"]:
        print("Some tests failed.", file=sys.stderr)
    else:
        print("All tests passed successfully.", file=sys.stderr)
    print(json.dumps(results_summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
