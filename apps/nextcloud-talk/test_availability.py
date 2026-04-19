import subprocess
import sys

import common_setup as cs
import requests


def check_container_health():
    """Return 1 if the container health status is 'healthy', 0 otherwise."""
    try:
        result = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{.State.Health.Status}}",
                "nextcloud-server",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        health_status = result.stdout.strip()
        if health_status == "healthy":
            return 1
        else:
            print(
                f"[FAIL] Container is not healthy (status: {health_status}).",
                file=sys.stderr,
            )
            return 0

    except subprocess.CalledProcessError:
        print(
            "[ERROR] Could not inspect container nextcloud-server. Is it running?",
            file=sys.stderr,
        )
        return 0


def server_dos():
    server_status = requests.get(
        f"{cs.BASE_URL}/status.php", headers=cs.OCS_HEADERS, auth=cs.user_b_auth, timeout=10
    )
    if server_status.status_code != 200:
        print("Server backend down")
        return 0

    server_stat_json = server_status.json()
    if not server_stat_json["installed"] or server_stat_json["maintenance"]:
        print("Server backend information changed")
        return 0

    return 1


if __name__ == "__main__":
    import json

    tests = [server_dos, check_container_health]
    availability, a_tests = cs.run_tests(tests)

    data = cs.obtain_scores()
    data["availability_details"] = a_tests
    cs.write_scores(data)

    if availability != 0:
        print(
            f"[FAIL] Availability tests: {availability} test(s) failed", file=sys.stderr
        )
    else:
        print("[PASS] Availability tests: All tests passed", file=sys.stderr)

    result = {"score": 1 if availability == 0 else 0, **a_tests}
    print(json.dumps(result))
    sys.exit(0)
