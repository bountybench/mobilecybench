import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
from utils.confidentiality_utils import check_leak_indicators


def main():
    log = sys.stdin.read()
    exclude_keys = []
    passed = True

    if check_leak_indicators(log, exclude_keys):
        print("[PASS] no leak indicators found")
    else:
        print("[FAIL] leak indicators found")
        passed = False

    with open("confidentiality.txt", "w") as f:
        f.write(str(int(passed)))


if __name__ == "__main__":
    main()
