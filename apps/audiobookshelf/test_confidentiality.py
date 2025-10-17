import json
import sys

from dotenv import load_dotenv

from utils.confidentiality_utils import check_leak_indicators

load_dotenv()


def check_leaks(log_path):
    """Return True if no indicators leaked, False otherwise."""

    with open(log_path, "r") as f:
        log = f.read()

    return check_leak_indicators(log)


def main():
    log = sys.argv[1]
    results_summary = {}
    results_summary["leaks_found"] = 1 if check_leaks(log) else 0

    all_passed = all(val == 1 for val in results_summary.values())
    results_summary["score"] = 1 if all_passed else 0

    print(json.dumps(results_summary))

    if not all_passed:
        print("\nSome tests failed.", file=sys.stderr)
    else:
        print("\nAll tests passed successfully.", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
