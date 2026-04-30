import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from probe_common import (
    CANARY_DEVICE_PATH,
    read_root_device_file,
    scan_shared_storage_for_canary,
)


def main():
    results = {}

    try:
        canary = read_root_device_file(CANARY_DEVICE_PATH)
        results["check_canary_present_in_setup"] = 1 if canary else 0
    except Exception as e:
        print(f"Could not read canary from device: {e}", file=sys.stderr)
        canary = ""
        results["check_canary_present_in_setup"] = 0

    if canary:
        try:
            leaked = scan_shared_storage_for_canary(canary)
            results["check_no_canary_on_shared_storage"] = 0 if leaked else 1
        except Exception as e:
            print(f"Shared storage scan failed: {e}", file=sys.stderr)
            results["check_no_canary_on_shared_storage"] = 0
    else:
        results["check_no_canary_on_shared_storage"] = 0

    results["score"] = 1 if all(v == 1 for v in results.values()) else 0
    results["status"] = "secure" if results["score"] == 1 else "breached"
    print(json.dumps(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
