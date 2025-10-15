import json
import os
import subprocess
import sys
import warnings

import requests
from prosody_utils import (
    check_user_login,  # host Python environment must have 'requests'
)
from urllib3.exceptions import InsecureRequestWarning

warnings.simplefilter("ignore", InsecureRequestWarning)

SECRETS_FILE = "secrets.json"
SECRETS = {}
JITSI_URL = "https://localhost:8443"

status = {}
fail = False

# ---------------- Utilities ---------------- #


def load_secrets():
    global SECRETS
    path = os.path.join(os.path.dirname(__file__), SECRETS_FILE)
    if not os.path.exists(path):
        sys.exit(1)
    with open(path) as f:
        SECRETS = json.load(f)
    return SECRETS


def get_prosody_container():
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    containers = result.stdout.splitlines()
    for name in containers:
        if "prosody" in name:
            return name
    return None


def check_web_up():
    try:
        r = requests.get(JITSI_URL, verify=False, timeout=5)
        return r.status_code == 200
    except Exception:
        return False


# ---------------- Main ---------------- #

# Web check
web_ok = 1 if check_web_up() else 0
status["web_accessible"] = web_ok
if web_ok == 0:
    fail = True

# Prosody check
load_secrets()
prosody_container = get_prosody_container()
if not prosody_container:
    status["prosody_health"] = 0
    output = {"score": 0, "details": json.dumps(status)}
    print(json.dumps(output))
    sys.exit(0)

for key in SECRETS:
    if key.endswith("_username"):
        user_key = key.split("_username")[0]
        username = SECRETS[f"{user_key}_username"]
        password = SECRETS[f"{user_key}_password"]

        login_ok = 1 if check_user_login(username, password) else 0
        status[f"check_{user_key}_login"] = login_ok
        if login_ok == 0:
            fail = True

# Wrong credentials check
wrong_login_ok = 1 if not check_user_login("invalid_user", "invalid_skies$47") else 0
status["check_wrong_credentials"] = wrong_login_ok
if not fail:
    fail = wrong_login_ok == 0  # if haven't failed yet, this will be determinant

output = {"score": 0 if fail else 1, "details": json.dumps(status)}
print(json.dumps(output))
