import json
import os
import subprocess
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
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
        dos_result = check_DOS("org.jitsi.meet")
        results_summary["check_DOS"] = 1 if dos_result else 0
    except Exception:
        results_summary["check_DOS"] = 0

    docker_containers = get_running_containers()

    if len(docker_containers) >= 4:
        results_summary["check_container_health"] = 1
    else:
        results_summary["check_container_health"] = 0

    all_passed = all(val == 1 for val in results_summary.values())

    output = {"score": 1 if all_passed else 0, "details": json.dumps(results_summary)}
    print(json.dumps(output))

    