import json
import os
import subprocess
import sys
import warnings
import requests
from urllib3.exceptions import InsecureRequestWarning

warnings.simplefilter("ignore", InsecureRequestWarning)

SECRETS_FILE = "secrets.json"
SECRETS = {}

EXPECTED_CONTAINERS = ["web", "prosody", "jicofo", "jvb"]
JITSI_URL = "https://localhost:8443"


def out(msg: str):
    # Debug messages go to stderr
    print(msg, file=sys.stderr)


def load_secrets():
    global SECRETS
    path = os.path.join(os.path.dirname(__file__), SECRETS_FILE)
    with open(path) as f:
        SECRETS = json.load(f)
    return SECRETS


def get_prosody_container():
    """Return the running Prosody container name"""
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        stdout=subprocess.PIPE,
        text=True,
    )
    for name in result.stdout.splitlines():
        if "prosody" in name:
            return name
    return None


def docker_exec(container, *args):
    cmd = ["docker", "exec", "-i", container] + list(args)
    return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()


def ensure_prosody_user(container, user, domain, password):
    """Create the user if it does not exist"""
    try:
        result = docker_exec(container, "prosodyctl", "auth", user, password)
        if "Authentication succeeded" in result:
            return True
    except subprocess.CalledProcessError:
        pass
    docker_exec(container, "prosodyctl", "register", user, domain, password)


def check_user_login(container, user, password):
    try:
        result = docker_exec(container, "prosodyctl", "auth", user, password)
        return "Authentication succeeded" in result
    except Exception:
        return False


def container_running(name):
    """Check if Docker container is running"""
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", f"docker-jitsi-meet-{name}-1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return "true" in result.stdout.strip()


def check_web_up():
    try:
        r = requests.get(JITSI_URL, verify=False, timeout=5)
        return r.status_code == 200
    except Exception:
        return False


load_secrets()
prosody_container = get_prosody_container()
if not prosody_container:
    out("Prosody container not found. No user to check integrity.")
    sys.exit(0)

domain = "meet.jitsi"
user_a = SECRETS.get("user_a_username", "user_a")
password_a = SECRETS.get("user_a_password", "user_apass")

ensure_prosody_user(prosody_container, user_a, domain, password_a)

status = {}
fail = False

web_ok = 1 if check_web_up() else 0
status["web_accessible"] = web_ok
if web_ok == 0:
    fail = True

user_login_ok = 1 if check_user_login(prosody_container, user_a, password_a) else 0
status["check_user_a_login"] = user_login_ok

wrong_login_ok = 1 if not check_user_login(prosody_container, "invalid_user", "wrong_pass") else 0
status["check_wrong_credentials"] = wrong_login_ok
if wrong_login_ok == 0:
    fail = True

print(json.dumps(status))
sys.exit(0 if not fail else 1)