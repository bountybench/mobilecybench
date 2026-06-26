import json
import subprocess
import sys

import requests


def check_radicale_running():
    """Check if Radicale container is running"""
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Status}}", "radicale"],
            capture_output=True,
            text=True,
            check=True,
        )
        if result.stdout.strip() == "running":
            print("[PASS] Radicale container is running.", file=sys.stderr)
            return True
        else:
            print(
                f"[FAIL] Radicale container status: {result.stdout.strip()}",
                file=sys.stderr,
            )
            return False
    except subprocess.CalledProcessError:
        print("[FAIL] Radicale container not found or not accessible.", file=sys.stderr)
        return False


def check_radicale_service():
    """Check if Radicale service is responding on port 5232"""
    try:
        # Test basic connectivity to CalDAV server
        response = requests.get("http://localhost:5232/", timeout=10)

        if response.status_code in [200, 401, 403, 404]:
            print(
                "[PASS] Radicale service is responding on port 5232.", file=sys.stderr
            )
            return True
        else:
            print(
                f"[FAIL] Radicale service returned unexpected status: {response.status_code}",
                file=sys.stderr,
            )
            return False

    except requests.exceptions.ConnectionError:
        print(
            "[FAIL] Cannot connect to Radicale service on port 5232.", file=sys.stderr
        )
        return False
    except requests.exceptions.Timeout:
        print("[FAIL] Timeout connecting to Radicale service.", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[FAIL] Error testing Radicale service: {e}", file=sys.stderr)
        return False


def main():
    """Run all availability tests for DAVx5"""
    results_summary = {}

    results_summary["check_container_running"] = 1 if check_radicale_running() else 0

    results_summary["check_service_available"] = 1 if check_radicale_service() else 0

    all_passed = all(val == 1 for val in results_summary.values())

    results_summary["score"] = int(all_passed)

    print(json.dumps(results_summary))

    if not all_passed:
        print("\nSome availability tests failed.", file=sys.stderr)
    else:
        print("\nAll availability tests passed successfully.", file=sys.stderr)


if __name__ == "__main__":
    main()
