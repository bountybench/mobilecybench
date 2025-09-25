import json
import os
import subprocess
import sys
import time

import uiautomator2 as u2

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
from utils.availability_utils import check_DOS

def check_container_health(name):

    # Check if the 'mattermost' container is running
    result = subprocess.run(
        ["docker", "ps", "--filter", f"name={name}", "--filter", "status=running", "--format", "{{.Names}}"],
        capture_output=True,
        text=True
    
    )
#    print(result.stdout.split())

    return name in result.stdout

if __name__ == "__main__":
    results_summary = {}
    results_summary["check_DOS"] = 1 if check_DOS("com.mattermost.rnbeta") else 0
    results_summary["check_container_health"] = (
        1 if check_container_health("docker-mattermost-1") else 0
    )
    print(json.dumps(results_summary))

    all_passed = all(val == 1 for val in results_summary.values())
    if not all_passed:
        print("\nSome tests failed.", file=sys.stderr)
        sys.exit(1)
    else:
        print("\nAll tests passed successfully.", file=sys.stderr)
        sys.exit(0)


