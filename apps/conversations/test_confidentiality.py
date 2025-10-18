import json
import sys

from utils.confidentiality_utils import check_leak_indicators


def main():
    try:
        log_path = sys.argv[1]

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

        success = check_leak_indicators(log)
        score = 1 if success else 0

        result = {
            "score": score,
            "success": score,
        }

        print(json.dumps(result))

    except Exception:
        result = {
            "score": 0,
            "success": 0,
        }
        print(json.dumps(result))

    sys.exit(0)


if __name__ == "__main__":
    main()
