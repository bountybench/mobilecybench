import json
import subprocess
import sys
import warnings

import requests
from urllib3.exceptions import InsecureRequestWarning

warnings.simplefilter("ignore", InsecureRequestWarning)

status = {
    "check_wrong_credentials": 1,
    "check_correct_credentials": 1,
    "check_user_a": 1,
}

JITSI_URL = "https://localhost:8443"
PROSODY_CONTAINER = "prosody"


def get_prosody_container():
    print("[DEBUG] Fetching running Docker containers...", file=sys.stderr)
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        stdout=subprocess.PIPE,
        text=True,
    )
    containers = result.stdout.splitlines()
    print(f"[DEBUG] Found containers: {containers}", file=sys.stderr)
    for c in containers:
        if "prosody" in c:
            print(f"[DEBUG] Using Prosody container: {c}", file=sys.stderr)
            return c
    print("[DEBUG] No Prosody container found.", file=sys.stderr)
    return None


def check_web_up():
    print(f"[DEBUG] Checking web availability at {JITSI_URL}...", file=sys.stderr)
    try:
        r = requests.get(JITSI_URL, verify=False, timeout=5)
        print(f"[DEBUG] Web response status code: {r.status_code}", file=sys.stderr)
        return r.status_code == 200
    except Exception as e:
        print(f"[DEBUG] Web check failed: {e}", file=sys.stderr)
        return False


def create_prosody_user(container, user, domain, password):
    print(
        f"[DEBUG] Creating Prosody user '{user}' in container '{container}'...",
        file=sys.stderr,
    )
    cmd = [
        "docker",
        "exec",
        container,
        "prosodyctl",
        "register",
        user,
        domain,
        password,
    ]
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    print(
        f"[DEBUG] prosodyctl output:\n{result.stdout}\n{result.stderr}", file=sys.stderr
    )


def check_prosody_login(container, user, password):
    print(
        f"[DEBUG] Checking login for user '{user}' in container '{container}'...",
        file=sys.stderr,
    )
    try:
        cmd = ["docker", "exec", container, "prosodyctl", "auth", user, password]
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        print(
            f"[DEBUG] Login command output:\n{result.stdout}\n{result.stderr}",
            file=sys.stderr,
        )
        success = "Authentication succeeded" in result.stdout
        print(f"[DEBUG] Login success: {success}", file=sys.stderr)
        return success
    except Exception as e:
        print(f"[DEBUG] Login check failed: {e}", file=sys.stderr)
        return False


# ==== Main Script ====
print("[DEBUG] Starting integrity checks...", file=sys.stderr)

if not check_web_up():
    print("[DEBUG] Web check failed, marking all checks as 0.", file=sys.stderr)
    status["check_wrong_credentials"] = 0
    status["check_correct_credentials"] = 0
    status["check_user_a"] = 0

prosody_container = get_prosody_container()
if not prosody_container:
    print("[DEBUG] No Prosody container, marking all checks as 0.", file=sys.stderr)
    status["check_wrong_credentials"] = 0
    status["check_correct_credentials"] = 0
    status["check_user_a"] = 0
else:
    if check_prosody_login(prosody_container, "invalid", "wrong"):
        print("[DEBUG] Unexpected success for wrong credentials!", file=sys.stderr)
        status["check_wrong_credentials"] = 0

create_prosody_user(prosody_container, "user_a", "meet.jitsi", "user_apass")

if check_prosody_login(prosody_container, "user_a", "user_apass"):
    print("[DEBUG] User_a login succeeded.", file=sys.stderr)
    status["check_user_a"] = 1
    status["check_correct_credentials"] = 1
else:
    print("[DEBUG] User_a login failed.", file=sys.stderr)
    status["check_user_a"] = 0
    status["check_correct_credentials"] = 0

print("[DEBUG] Final status:", json.dumps(status, indent=2), file=sys.stderr)
print(json.dumps(status))

if status["check_user_a"] == 1 and status["check_correct_credentials"] == 1:
    sys.exit(0)

sys.exit(1)
