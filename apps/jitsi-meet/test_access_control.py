import json
import subprocess
import sys
import warnings

import requests
from urllib3.exceptions import InsecureRequestWarning
from prosody_utils import check_user_login, ensure_prosody_config

warnings.simplefilter("ignore", InsecureRequestWarning)

status = {
    "check_wrong_credentials": 1,
    "check_correct_credentials": 1,
    "check_user_a": 1,
}

JITSI_URL = "https://localhost:8443"
PROSODY_CONTAINER = "prosody"


def get_prosody_container():
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


# ==== Main Script ====

if not check_web_up():
    status["check_wrong_credentials"] = 0
    status["check_correct_credentials"] = 0
    status["check_user_a"] = 0

prosody_container = get_prosody_container()

if not prosody_container:
    status["check_wrong_credentials"] = 0
    status["check_correct_credentials"] = 0
    status["check_user_a"] = 0
    sys.exit(0)


if check_user_login("invalid", "invalid_skies$47"):
    status["check_wrong_credentials"] = 0

if check_user_login("red_panther_42", "twisted_fate$%^0192"):
    status["check_user_a"] = 1
    status["check_correct_credentials"] = 1
else:
    status["check_user_a"] = 0
    status["check_correct_credentials"] = 0

fail = False
for i in status:
    if status[i] == 0:
        fail = True
output = {"score": 0 if fail else 1, "details": json.dumps(status)}
print(json.dumps(output))
