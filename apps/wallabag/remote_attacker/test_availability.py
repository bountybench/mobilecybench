import json
import os
import subprocess
import sys
import time

import requests


def check_server_accessible():
    ca_bundle = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "tls", "rootCA.pem"
    )
    verify = ca_bundle if os.path.exists(ca_bundle) else True
    last_err = None
    for _ in range(10):
        try:
            r = requests.get("https://localhost:8080/login", timeout=5, verify=verify)
            if r.status_code == 200:
                return 1
            last_err = f"status={r.status_code}"
        except Exception as e:
            last_err = str(e)
        time.sleep(1)
    print(f"Server connection failed: {last_err}", file=sys.stderr)
    return 0


def check_container_healthy():
    last_status = ""
    for _ in range(10):
        try:
            result = subprocess.run(
                [
                    "docker",
                    "inspect",
                    "wallabag",
                    "--format",
                    "{{.State.Health.Status}}",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            last_status = result.stdout.strip()
            if last_status == "healthy":
                return 1
        except Exception as e:
            last_status = str(e)
        time.sleep(1)
    print(f"Container health status: {last_status}", file=sys.stderr)
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
