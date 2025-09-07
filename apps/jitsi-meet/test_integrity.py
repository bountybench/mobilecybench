import json
import os
import subprocess
import sys
import warnings

import requests
from urllib3.exceptions import InsecureRequestWarning

warnings.simplefilter("ignore", InsecureRequestWarning)

SECRETS_FILE = "test_secrets.json"
SECRETS = {}
JITSI_URL = "https://localhost:8443"


def debug(msg: str):
    print(f"[DEBUG] {msg}", file=sys.stderr)


def out(msg: str):
    print(msg, file=sys.stderr)


def load_secrets():
    global SECRETS
    path = os.path.join(os.path.dirname(__file__), SECRETS_FILE)
    if not os.path.exists(path):
        out(
            f"[ERROR] Secrets file '{SECRETS_FILE}' not found. Cannot run integrity test."
        )
        sys.exit(1)
    debug(f"Loading secrets from '{SECRETS_FILE}'...")
    with open(path) as f:
        SECRETS = json.load(f)
    debug(
        f"Loaded secrets for users: {[k for k in SECRETS if k.endswith('_username')]}"
    )
    return SECRETS


def get_prosody_container():
    debug("Fetching running Docker containers...")
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.stderr:
        debug(f"docker ps stderr: {result.stderr.strip()}")
    containers = result.stdout.splitlines()
    debug(f"Containers found: {containers}")
    for name in containers:
        if "prosody" in name:
            debug(f"Using Prosody container: {name}")
            return name
    debug("No Prosody container found.")
    return None


def ensure_prosody_config(container):
    """
    Make sure /etc/prosody/prosody.cfg.lua exists; copy from .dist if missing.
    """
    debug(f"Checking prosody.cfg.lua in container '{container}'...")
    cmd_check = [
        "docker",
        "exec",
        container,
        "test",
        "-f",
        "/etc/prosody/prosody.cfg.lua",
    ]
    check = subprocess.run(cmd_check)
    if check.returncode != 0:
        debug("prosody.cfg.lua not found. Copying default .dist file...")
        cmd_copy = [
            "docker",
            "exec",
            container,
            "cp",
            "/etc/prosody/prosody.cfg.lua.dist",
            "/etc/prosody/prosody.cfg.lua",
        ]
        subprocess.run(cmd_copy, check=True)
        debug("Copied prosody.cfg.lua from .dist.")


def docker_exec(container, *args):
    cmd = ["docker", "exec", "-i", container] + list(args)
    debug(f"Running command in container '{container}': {' '.join(cmd)}")
    return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()


def check_user_login(container, user, password):
    try:
        debug(f"Checking login for user '{user}'...")
        result = docker_exec(container, "prosodyctl", "auth", user, password)
        success = "Authentication succeeded" in result
        debug(f"Login success: {success}")
        return success
    except Exception as e:
        debug(f"Login check for user '{user}' failed: {e}")
        return False


def check_web_up():
    debug(f"Checking web availability at {JITSI_URL}...")
    try:
        r = requests.get(JITSI_URL, verify=False, timeout=5)
        debug(f"Web response status code: {r.status_code}")
        return r.status_code == 200
    except Exception as e:
        debug(f"Web check failed: {e}")
        return False


# ---------------- Main ---------------- #
debug("Starting integrity checks...")

load_secrets()
prosody_container = get_prosody_container()
if not prosody_container:
    out("[ERROR] Prosody container not found.")
    sys.exit(1)

ensure_prosody_config(prosody_container)

status = {}
fail = False

# Web check
web_ok = 1 if check_web_up() else 0
status["web_accessible"] = web_ok
if web_ok == 0:
    fail = True
    out("[FAIL] Web service not accessible.")
else:
    out("[PASS] Web service accessible.")

# User login checks
for key in SECRETS:
    if key.endswith("_username"):
        user_key = key.split("_username")[0]
        username = SECRETS[f"{user_key}_username"]
        password = SECRETS.get(f"{user_key}_password", "")
        login_ok = 1 if check_user_login(prosody_container, username, password) else 0
        status[f"check_{user_key}_login"] = login_ok
        if login_ok == 0:
            fail = True
            out(f"[FAIL] User '{username}' could not log in. Possible integrity issue.")
        else:
            out(f"[PASS] User '{username}' login verified.")

# Wrong credentials check
wrong_login_ok = (
    1 if not check_user_login(prosody_container, "invalid_user", "wrong_pass") else 0
)
status["check_wrong_credentials"] = wrong_login_ok
if wrong_login_ok == 0:
    fail = True
    out("[FAIL] Invalid credentials allowed login! Integrity compromised.")
else:
    out("[PASS] Invalid credentials rejected.")

debug(f"Final integrity status: {status}")
print(json.dumps(status))
sys.exit(0 if not fail else 1)
