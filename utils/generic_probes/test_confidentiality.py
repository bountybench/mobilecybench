import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
from utils.confidentiality_utils import check_leak_indicators
from utils.generic_probes.helpers import get_metadata


# Invoke individually with `python3 utils/generic_probes/test_confidentiality.py apps/home-assistant-android`
# Requires `metadata.json` to have `excluded_keys`: list[string] property
# Exits with code 0 if all tests pass, 1 if any test fails, 2 if metadata is not found or valid
def main():
    metadata = get_metadata()

    excluded_keys = metadata.get("excluded_keys", [])

    if not isinstance(excluded_keys, list):
        print("Your metadata's excluded_keys is not a list")
        return 2

    log = sys.stdin.read()

    if not check_leak_indicators(log, excluded_keys):
        print("Some tests failed.", file=sys.stderr)
        return 1
    else:
        print("All tests passed successfully.", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
