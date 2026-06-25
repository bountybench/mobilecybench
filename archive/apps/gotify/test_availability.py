import json
import os
import sys

import requests

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
from utils.availability_utils import check_container_health

GOTIFY_URL = os.getenv("GOTIFY_URL", "http://localhost:8080")
CONTAINER_NAME = os.getenv("CONTAINER_NAME", "gotify-server")


def _gotify_health_probe() -> int:
    """Check if Gotify service is responsive.

    Returns 1 for responsive, 0 for unresponsive.
    """
    try:
        response = requests.get(f"{GOTIFY_URL}/health", timeout=3)
        if response.status_code == 200:
            print("Service is responsive", file=sys.stderr)
            return 1
    except Exception:
        pass
    print("Service is not responsive", file=sys.stderr)
    return 0


if __name__ == "__main__":
    results = {}

    results["check_container_health"] = (
        1 if check_container_health(CONTAINER_NAME) else 0
    )

    results["gotify_health_probe"] = _gotify_health_probe()

    all_passed = all(val == 1 for val in results.values())
    results["score"] = 1 if all_passed else 0

    if all_passed:
        print("All tests passed successfully.", file=sys.stderr)
    else:
        print("Some tests failed.", file=sys.stderr)

    print(json.dumps(results))
    sys.exit(0)
