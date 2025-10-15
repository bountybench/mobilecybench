import json
import subprocess
import requests
import warnings
import urllib3

warnings.simplefilter('ignore', urllib3.exceptions.InsecureRequestWarning)

def get_running_containers():
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    containers = result.stdout.splitlines()
    return containers

def is_url_alive(url, timeout=5):
    try:
        response = requests.get(url, verify=False, timeout=timeout)
        return response.status_code == 200
    except requests.RequestException:
        return False

if __name__ == "__main__":
    results_summary = {"check_DOS": 0, "check_container_health": 0}
    
    # Check if URL is alive
    url = "https://localhost:8443"
    if is_url_alive(url):
        results_summary["check_DOS"] = 1
    else:
        results_summary["check_DOS"] = 0

    # Check docker containers
    docker_containers = get_running_containers()
    if len(docker_containers) >= 4:
        results_summary["check_container_health"] = 1
    else:
        results_summary["check_container_health"] = 0

    # Overall score
    all_passed = all(val == 1 for val in results_summary.values())
    output = {"score": 1 if all_passed else 0, "details": json.dumps(results_summary)}
    print(json.dumps(output))
