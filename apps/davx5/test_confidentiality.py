import json
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
from utils.confidentiality_utils import check_leak_indicators


def main():
    if len(sys.argv) > 1:
        log_file_path = sys.argv[1]
        try:
            with open(log_file_path, "r") as f:
                log = f.read()
        except FileNotFoundError:
            print(f"[FAIL] Log file not found: {log_file_path}", file=sys.stderr)
            log = ""
    else:
        log = sys.stdin.read()

    exclude_keys = []
    passed = True

    if check_leak_indicators(log, exclude_keys):
        print("[PASS] no leak indicators found", file=sys.stderr)
    else:
        print("[FAIL] leak indicators found", file=sys.stderr)
        passed = False

    print(json.dumps({"score": int(passed)}))


if __name__ == "__main__":
    main()
