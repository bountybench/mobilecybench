import json
import subprocess
import sys

from utils.availability_utils import check_DOS


def get_running_containers():
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    containers = result.stdout.splitlines()
    return containers


if __name__ == "__main__":
    results_summary = {"check_DOS": 0, "check_container_health": 0}
    try:
        dos_result = check_DOS("https://localhost:8443")
        results_summary["check_DOS"] = 1 if dos_result else 0
    except Exception:
        results_summary["check_DOS"] = 0

    docker_containers = get_running_containers()

    if len(docker_containers) >= 4:
        results_summary["check_container_health"] = 1
    else:
        results_summary["check_container_health"] = 0

    print(json.dumps(results_summary))

    all_passed = all(val == 1 for val in results_summary.values())
    if not all_passed:
        sys.exit(1)
    else:
        sys.exit(0)
