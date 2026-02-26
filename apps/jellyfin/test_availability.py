import json
import os
import socket
import sys

import requests

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
from utils.availability_utils import check_container_health

JELLYFIN_HOST = os.getenv("JELLYFIN_HOST", "localhost")
JELLYFIN_PORT = int(os.getenv("JELLYFIN_PORT", "8096"))
AVAIL_TIMEOUT = int(os.getenv("AVAIL_TIMEOUT", "5"))
CONTAINER_NAME = os.getenv("CONTAINER_NAME", "jellyfin-server")

JELLYFIN_BASE_URL = f"http://{JELLYFIN_HOST}:{JELLYFIN_PORT}"


def _jellyfin_http_probe() -> int:
    """Probe Jellyfin HTTP port connectivity.

    Returns 1 for successful connection, 0 for connection failure.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((JELLYFIN_HOST, JELLYFIN_PORT))
        sock.close()
        return 1 if result == 0 else 0
    except Exception:
        return 0


def _jellyfin_health_check() -> int:
    """Check Jellyfin health endpoint.

    Returns 1 for healthy, 0 for unhealthy or unreachable.
    """
    try:
        response = requests.get(f"{JELLYFIN_BASE_URL}/health", timeout=AVAIL_TIMEOUT)
        return 1 if response.status_code == 200 else 0
    except Exception:
        return 0


def _jellyfin_api_probe() -> int:
    """Probe Jellyfin API availability.

    Returns 1 for accessible, 0 for inaccessible.
    """
    try:
        response = requests.get(
            f"{JELLYFIN_BASE_URL}/System/Info/Public", timeout=AVAIL_TIMEOUT
        )
        return 1 if response.status_code == 200 else 0
    except Exception:
        return 0


if __name__ == "__main__":
    results = {}

    results["check_container_health"] = (
        1 if check_container_health(CONTAINER_NAME) else 0
    )

    http_ok = _jellyfin_http_probe()
    results["jellyfin_http_port_accessible"] = http_ok
    if http_ok:
        print(f"[PASS] Jellyfin HTTP port {JELLYFIN_PORT} accessible", file=sys.stderr)
    else:
        print(
            f"[FAIL] Jellyfin HTTP port {JELLYFIN_PORT} not accessible",
            file=sys.stderr,
        )

    health_ok = _jellyfin_health_check()
    results["jellyfin_health_endpoint"] = health_ok
    if health_ok:
        print("[PASS] Jellyfin health endpoint responding", file=sys.stderr)
    else:
        print("[FAIL] Jellyfin health endpoint not responding", file=sys.stderr)

    api_ok = _jellyfin_api_probe()
    results["jellyfin_api_accessible"] = api_ok
    if api_ok:
        print("[PASS] Jellyfin API accessible", file=sys.stderr)
    else:
        print("[FAIL] Jellyfin API not accessible", file=sys.stderr)

    all_passed = all(val == 1 for val in results.values())
    results["score"] = 1 if all_passed else 0

    if all_passed:
        print("All tests passed successfully.", file=sys.stderr)
    else:
        print("Some tests failed.", file=sys.stderr)

    print(json.dumps(results))
    sys.exit(0)
