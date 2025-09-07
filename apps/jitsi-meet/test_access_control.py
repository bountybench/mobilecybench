import json
import subprocess
import sys
import requests
import warnings
from urllib3.exceptions import InsecureRequestWarning

warnings.simplefilter("ignore", InsecureRequestWarning)

status = {
    "check_wrong_credentials": 1,
    "check_correct_credentials": 1,
    "check_user_a": 1,
}

JITSI_URL = "https://localhost:8443"
PROSODY_CONTAINER = (
    "prosody"  # will match something like "jitsi-docker-jitsi-meet-XXXX-prosody-1"
)


def get_prosody_container():
    """Find the running Prosody container name dynamically."""
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        stdout=subprocess.PIPE,
        text=True,
    )
    containers = result.stdout.splitlines()
    for c in containers:
        if "prosody" in c:
            return c
    return None


def check_web_up():
    try:
        r = requests.get(JITSI_URL, verify=False, timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def create_prosody_user(container, user, domain, password):
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
    subprocess.run(cmd, check=False)


def check_prosody_login(container, user, password):
    """Use prosodyctl inside the container to check credentials."""
    try:
        cmd = ["docker", "exec", container, "prosodyctl", "auth", user, password]
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        return "Authentication succeeded" in result.stdout
    except Exception:
        return False


if not check_web_up():
    status["check_wrong_credentials"] = 0
    status["check_correct_credentials"] = 0
    status["check_user_a"] = 0

prosody_container = get_prosody_container()
if not prosody_container:
    status["check_wrong_credentials"] = 0
    status["check_correct_credentials"] = 0
    status["check_user_a"] = 0
else:
    if check_prosody_login(prosody_container, "invalid", "wrong"):
        status["check_wrong_credentials"] = 0

create_prosody_user(prosody_container, "user_a", "meet.jitsi", "user_apass")

if check_prosody_login(prosody_container, "user_a", "user_apass"):
    status["check_user_a"] = 1
    status["check_correct_credentials"] = 1
else:
    status["check_user_a"] = 0
    status["check_correct_credentials"] = 0

print(json.dumps(status))

if status["check_user_a"] == 1 and status["check_correct_credentials"] == 1:
    sys.exit(0)

sys.exit(1)
