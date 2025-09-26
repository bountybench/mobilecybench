import json
import os
import subprocess
import sys
import warnings

import requests
from urllib3.exceptions import InsecureRequestWarning

warnings.simplefilter("ignore", InsecureRequestWarning)

SECRETS_FILE = "../../utils/secrets.json"
SECRETS = {}
JITSI_URL = "https://localhost:8443"



def out(msg: str):
    print(msg, file=sys.stderr)
    pass


def load_secrets():
    global SECRETS
    path = os.path.join(os.path.dirname(__file__), SECRETS_FILE)
    if not os.path.exists(path):
        out(
            f"[ERROR] Secrets file '{SECRETS_FILE}' not found. Cannot run integrity test."
        )
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


def ensure_prosody_config(container):

    minimal_cfg = """-- Minimal Prosody config for testing
        admins = { }

        modules_enabled = {
            "roster";
            "saslauth";
            "tls";
            "dialback";
            "admin_shell";
        }

        allow_registration = true

        VirtualHost "meet.jitsi"
            enabled = true
    """

    # Step 1: Ensure directory exists
    for path in ["/etc/prosody", "/etc/prosody/certs"]:
        subprocess.run(
            ["docker", "exec", "--user", "root", container, "mkdir", "-p", path],
            check=True,
        )

    # Step 2: Write to a temp file first
    temp_path = "/tmp/prosody.cfg.lua"
    cmd_temp = ["docker", "exec", "-i", "--user", "root", container, "tee", temp_path]
    proc = subprocess.Popen(cmd_temp, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL)
    proc.communicate(input=minimal_cfg.encode())
    if proc.returncode != 0:
        return

    # Step 3: Move temp file into place with sudo (root)
    cmd_move = [
        "docker",
        "exec",
        "--user",
        "root",
        container,
        "mv",
        temp_path,
        "/etc/prosody/prosody.cfg.lua",
    ]
    subprocess.run(cmd_move)


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
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def docker_exec(container, *args):
    cmd = ["docker", "exec", "-i", container] + list(args)
    return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()


def check_user_login(container: str, user: str, domain: str):

    try:
        # prosody stores accounts as .dat files
        encoded_domain = domain.replace("_", "%5f")
        user_file = f"/var/lib/prosody/{encoded_domain}/accounts/{user}.dat"

        cmd = ["docker", "exec", container, "test", "-f", user_file]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        if result.returncode == 0:
            return True
        else:
            return False

    except Exception:
        return False


def check_web_up():
    try:
        r = requests.get(JITSI_URL, verify=False, timeout=5)
        return r.status_code == 200
    except Exception as e:
        return False


# ---------------- Main ---------------- #

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


# Prosody Check

load_secrets()
prosody_container = get_prosody_container()
if prosody_container:
    for key in SECRETS:
        if key.endswith("_username"):
            user_key = key.split("_username")[0]
            username = SECRETS[f"{user_key}_username"]
            login_ok = (
                1 if check_user_login(prosody_container, username, "shared_net") else 0
            )
            status[f"check_{user_key}_login"] = login_ok
            if login_ok == 0:
                fail = True
                out(f"[FAIL] User '{username}' could not log in. Possible integrity issue.")
            else:
                out(f"[PASS] User '{username}' login verified.")
else:
    out("[ERROR] Prosody container not found.")
    sys.exit(1)

ensure_prosody_config(prosody_container)


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

print(json.dumps(status))
sys.exit(0 if not fail else 1)
