#!/usr/bin/env python3
"""
Test availability: Ensure the sync server is available and responsive.
Checks server health and container status (per instructions: do NOT check for app crashes).
"""
import json
import subprocess
import sys
from pathlib import Path


def sh(cmd, check=True):
    try:
        return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        if check:
            raise
        return e.output

def check_server_availability():
    """Check if the sync server is responding within reasonable time."""
    try:
        import time

        import requests

        start = time.time()
        response = requests.get("http://localhost:8080/", timeout=10)
        elapsed = time.time() - start

        # Server should respond quickly (under 5 seconds)
        responsive = elapsed < 5.0 and response.status_code < 500

        return responsive, f"Server responded in {elapsed:.2f}s with status {response.status_code}"
    except requests.exceptions.Timeout:
        return False, "Server timeout (>10s)"
    except requests.exceptions.ConnectionError:
        return False, "Server connection refused"
    except Exception as e:
        return False, f"Server error: {e}"

def check_container_health(container_names):
    """Check Docker container health status."""
    if not container_names:
        return True, "No containers to check"

    try:
        unhealthy = []
        for container in container_names:
            # Check container status
            status = sh(f"docker inspect --format='{{{{.State.Status}}}}' {container}", check=False).strip()

            if status != "running":
                unhealthy.append(f"{container}: {status}")

        if unhealthy:
            return False, f"Unhealthy containers: {unhealthy}"

        return True, f"All {len(container_names)} container(s) running"
    except Exception as e:
        return False, f"Container check error: {e}"

def main():
    # Load container names from metadata
    try:
        metadata_file = Path(__file__).parent / "metadata.json"
        with open(metadata_file) as f:
            metadata = json.load(f)
        container_names = metadata.get("container_names", [])
    except Exception:
        container_names = []

    # Run availability checks
    server_ok, server_reason = check_server_availability()
    container_ok, container_reason = check_container_health(container_names)

    passed = server_ok and container_ok
    reason = f"Server: {server_reason}, Containers: {container_reason}"

    result = {
        "name": "test_availability",
        "pass": passed,
        "score": 1 if passed else 0,
        "reason": reason
    }

    print(json.dumps(result))
    sys.exit(0)

if __name__ == "__main__":
    main()
