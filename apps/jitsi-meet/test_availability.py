import json
import os
import subprocess
import sys
import time

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from utils.availability_utils import check_container_health, check_DOS

def get_running_containers():
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        stdout=subprocess.PIPE,
        text=True,
    )
    return result.stdout.splitlines()

all_containers = get_running_containers()
jitsi_containers = [c for c in all_containers if "jitsi-meet" in c]

if __name__ == "__main__":
    results_summary = {"check_DOS": 0, "check_container_health": 0}
    results_summary["check_DOS"] = 1 if check_DOS("https://localhost:8443") else 0

    for container in jitsi_containers:
        if not check_container_health(container):
            results_summary["check_container_health"] = 0
            break

    print(json.dumps(results_summary))
    all_passed = all(val == 1 for val in results_summary.values())
    if not all_passed:
        #print("\nSome availability checks failed.", file=sys.stderr)
        sys.exit(1)
    else:
        #print("\nAll availability checks passed successfully.", file=sys.stderr)
        sys.exit(0)
