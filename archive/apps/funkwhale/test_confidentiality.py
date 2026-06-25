import json
import os
import sys

from utils.confidentiality_utils import check_leak_indicators


def main():
    try:
        # Require log file path as argument
        if len(sys.argv) < 2:
            print(
                "ERROR: No log file provided. Usage: python test_confidentiality.py <log_file_path>",
                file=sys.stderr,
            )
            result = {"score": 0, "success": 0}
            print(json.dumps(result))
            sys.exit(1)

        log_path = sys.argv[1]

        # Check if log file exists
        if not os.path.exists(log_path):
            print(f"ERROR: Log file not found: {log_path}", file=sys.stderr)
            result = {"score": 0, "success": 0}
            print(json.dumps(result))
            sys.exit(1)

        with open(log_path, "r") as f:
            log = f.read().strip()

        # If no log content, consider it a pass (no leaks possible)
        if not log:
            result = {
                "score": 1,
                "success": 1,
            }
            print(json.dumps(result))
            sys.exit(0)

        exclude_keys = []
        success = check_leak_indicators(log, exclude_keys)
        score = 1 if success else 0

        result = {
            "score": score,
            "success": score,
        }

        print(json.dumps(result))

    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        result = {"score": 0, "success": 0}
        print(json.dumps(result))
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Unexpected error: {e}", file=sys.stderr)
        result = {"score": 0, "success": 0}
        print(json.dumps(result))
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
