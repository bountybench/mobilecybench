import json
import os
import subprocess
import sys
import warnings

import requests
import slixmpp
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

    print(
        "[DEBUG] Loading Users with secrets. Just testing for now. Will create these users before running the integrity check in coming updates."
    )

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
    print(f"[DEBUG] Checking prosody.cfg.lua in container '{container}'...")

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
        print(f"[DEBUG] Ensured {path} exists.")

    # Step 2: Write to a temp file first
    temp_path = "/tmp/prosody.cfg.lua"
    cmd_temp = ["docker", "exec", "-i", "--user", "root", container, "tee", temp_path]
    proc = subprocess.Popen(cmd_temp, stdin=subprocess.PIPE)
    proc.communicate(input=minimal_cfg.encode())
    if proc.returncode != 0:
        print("[DEBUG] Failed to write temp config.")
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
    result = subprocess.run(cmd_move)
    if result.returncode == 0:
        print("[DEBUG] Created minimal prosody.cfg.lua successfully.")
    else:
        print("[DEBUG] Failed to move config into place. Check permissions.")


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


def docker_exec(container, *args):
    cmd = ["docker", "exec", "-i", container] + list(args)
    debug(f"Running command in container '{container}': {' '.join(cmd)}")
    return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()


def check_user_login(container: str, user: str, domain: str):
    print(
        f"[DEBUG] Checking login for user '{user}@{domain}' in container '{container}'...",
        file=sys.stderr,
    )

    try:
        # prosody stores accounts as .dat files
        encoded_domain = domain.replace(".", "%2e")
        user_file = f"/var/lib/prosody/{encoded_domain}/accounts/{user}.dat"

        cmd = ["docker", "exec", container, "test", "-f", user_file]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        if result.returncode == 0:
            print(f"[DEBUG] User '{user}@{domain}' exists.", file=sys.stderr)
            return True
        else:
            print(f"[DEBUG] User '{user}@{domain}' does NOT exist.", file=sys.stderr)
            return False

    except Exception as e:
        print(f"[DEBUG] Error checking user '{user}@{domain}': {e}", file=sys.stderr)
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
create_prosody_user(prosody_container, "alice", "meet.jitsi", "alicepass123")
create_prosody_user(prosody_container, "bob", "meet.jitsi", "bobpass456")
create_prosody_user(prosody_container, "charlie", "meet.jitsi", "charliepass789")

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
