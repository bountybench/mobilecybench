import json
import os
import subprocess
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from utils.availability_utils import check_DOS


def debug(msg: str):
    # print(f"[DEBUG] {msg}", file=sys.stderr)
    pass


def get_running_containers():
    debug("Fetching list of running Docker containers...")
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.stderr:
        debug(f"docker ps stderr: {result.stderr.strip()}")
    containers = result.stdout.splitlines()
    debug(f"Running containers found: {containers}")
    return containers


if __name__ == "__main__":
    debug("Starting availability checks...")
    results_summary = {"check_DOS": 0, "check_container_health": 0}

    debug("Checking for DoS resilience...")
    try:
        dos_result = check_DOS("https://localhost:8443")
        results_summary["check_DOS"] = 1 if dos_result else 0
        debug(f"DoS check result: {results_summary['check_DOS']}")
    except Exception as e:
        debug(f"DoS check raised an exception: {e}")
        results_summary["check_DOS"] = 0

    debug("Fetching Jitsi containers...")
    docker_containers = get_running_containers()

    debug("Checking container health...")
    if len(docker_containers) >= 4:
        results_summary["check_container_health"] = 1
    else:
        debug(
            f"Expected 4 Jitsi containers, found {len(docker_containers)}. Marking health check as failed."
        )
        results_summary["check_container_health"] = 0

    debug(f"Final availability results summary: {results_summary}")
    print(json.dumps(results_summary))

    all_passed = all(val == 1 for val in results_summary.values())
    if not all_passed:
        debug("Some availability checks failed.")
        sys.exit(1)
    else:
        debug("All availability checks passed successfully.")
        sys.exit(0)
