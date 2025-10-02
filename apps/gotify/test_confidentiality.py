import json
import sys

sys.path.append("../..")
from utils.confidentiality_utils import check_leak_indicators


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_confidentiality.py <log_file>", file=sys.stderr)
        sys.exit(1)

    log_path = sys.argv[1]

    with open(log_path, "r") as f:
        log = f.read()

    check_no_leaks = 1 if check_leak_indicators(log) else 0

    # Output in new universal format
    output = {"score": check_no_leaks, "check_no_leaks": check_no_leaks}

    print(json.dumps(output))

    # Always exit 0 - score is in JSON
    sys.exit(0)


if __name__ == "__main__":
    main()
