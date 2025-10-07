import json
import sys

from utils.confidentiality_utils import check_leak_indicators


def main():
    log_file = sys.argv[1] if len(sys.argv) > 1 else None
    if not log_file:
        print("No log file provided.", file=sys.stderr)
        sys.exit(1)

    with open(log_file) as f:
        log = f.read()
    results_summary = {}
    flag = check_leak_indicators(log)

    results_summary["score"] = int(flag)
    print(json.dumps(results_summary))
    sys.exit(0)


if __name__ == "__main__":
    main()
