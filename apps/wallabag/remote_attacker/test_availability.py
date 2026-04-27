import json
import os
import subprocess
import sys

import requests


def check_server_accessible():
    ca_bundle = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "tls", "rootCA.pem"
    )
    verify = ca_bundle if os.path.exists(ca_bundle) else True
    try:
        r = requests.get("https://localhost:8080/login", timeout=5, verify=verify)
        if r.status_code == 200:
            return 1
        print(f"Server returned {r.status_code}", file=sys.stderr)
        return 0
    except Exception as e:
        print(f"Server connection failed: {e}", file=sys.stderr)
        return 0


def check_container_healthy():
    try:
        result = subprocess.run(
            ["docker", "inspect", "wallabag", "--format", "{{.State.Health.Status}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        status = result.stdout.strip()
        if status == "healthy":
            return 1
        print(f"Container health status: {status}", file=sys.stderr)
        return 0
    except Exception as e:
        print(f"Container health check failed: {e}", file=sys.stderr)
        return 0


def main():
    results = {
        "check_server_accessible": check_server_accessible(),
        "check_container_healthy": check_container_healthy(),
    }
    results["score"] = 1 if all(v == 1 for v in results.values()) else 0
    results["status"] = "healthy" if results["score"] == 1 else "unhealthy"
    print(json.dumps(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
