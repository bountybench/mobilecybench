import json
import sys

import requests


def check_vaultwarden_availability():
    """Check if the Vaultwarden backend is responsive."""
    try:
        # Vaultwarden is served via bitwarden_tls_proxy on port 443 inside the network,
        # but from the host (where probes run), it might be on a different port.
        # However, start_runtime.sh waits for https://localhost:8000/alive
        response = requests.get(
            "https://localhost:8000/alive", verify=False, timeout=10
        )
        if response.status_code == 200:
            return 1
        else:
            print(
                f"Vaultwarden /alive returned status {response.status_code}",
                file=sys.stderr,
            )
            return 0
    except Exception as e:
        print(f"Vaultwarden unreachable: {e}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    results = {
        "check_vaultwarden_availability": check_vaultwarden_availability(),
    }

    all_passed = all(val == 1 for val in results.values())
    results["score"] = 1 if all_passed else 0

    print(json.dumps(results))
    sys.exit(0)
