import json
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote

import requests
from dotenv import load_dotenv
from requests.exceptions import JSONDecodeError

load_dotenv()

SCRIPT_DIR = Path(__file__).resolve().parent
METADATA_PATH = SCRIPT_DIR / "metadata.json"
TLS_CA_BUNDLE = SCRIPT_DIR / "../../tls/a310d694.0"

with open(METADATA_PATH, "r") as f:
    _metadata = json.load(f)


def get_emulator_server(metadata=None):
    metadata = metadata or _metadata
    emulator_server = metadata.get("emulator_server")
    if not emulator_server:
        raise ValueError("metadata.json missing required field: emulator_server")
    if "://" not in emulator_server:
        raise ValueError(
            "metadata.json emulator_server must include a scheme (expected http:// or https://)"
        )
    return emulator_server


def get_host_base_url(metadata=None):
    return get_emulator_server(metadata).replace("10.0.2.2", "localhost")


def get_trusted_domain(metadata=None):
    emulator_server = get_emulator_server(metadata)
    return emulator_server.split("://", 1)[1]


def ensure_requests_ca_bundle(base_url):
    if base_url.startswith("https://") and "REQUESTS_CA_BUNDLE" not in os.environ:
        os.environ["REQUESTS_CA_BUNDLE"] = str(TLS_CA_BUNDLE)


def require_env(name: str) -> str:
    value = os.getenv(name)
    if value is None:
        raise RuntimeError(f"Required environment variable not set: {name}")
    return value


# Load env variables — names mirror .env keys for a single source of truth.
ADMIN_USERNAME = require_env("ADMIN_USERNAME")
ADMIN_PASSWORD = require_env("ADMIN_PASSWORD")
USER_A_USERNAME = require_env("USER_A_USERNAME")
USER_A_PASSWORD = require_env("USER_A_PASSWORD")
USER_B_USERNAME = require_env("USER_B_USERNAME")
USER_B_PASSWORD = require_env("USER_B_PASSWORD")
USER_B_EMAIL = require_env("USER_B_EMAIL")
USER_B_MESSAGE = require_env("USER_B_MESSAGE")
ADMIN_FILE_CONTENTS = require_env("ADMIN_FILE_CONTENTS")
ADMIN_FILE_NAME = require_env("ADMIN_FILE_NAME")
USER_B_FILE_CONTENTS = require_env("USER_B_FILE_CONTENTS")
USER_B_FILE_NAME = require_env("USER_B_FILE_NAME")

BASE_URL = get_host_base_url()
ensure_requests_ca_bundle(BASE_URL)
OCS_HEADERS = {
    "OCS-APIRequest": "true",
    "Accept": "application/json",
    "Content-Type": "application/json",
}
REQUEST_TIMEOUT = 10
admin_auth = (ADMIN_USERNAME, ADMIN_PASSWORD)
user_a_auth = (USER_A_USERNAME, USER_A_PASSWORD)
user_b_auth = (USER_B_USERNAME, USER_B_PASSWORD)

SCORE_FILE = "scores.json"
DAV_NS = {"d": "DAV:"}

ADB_BIN = "adb"
TALK_PACKAGE = "com.nextcloud.talk2"

# Snake-case keys written to secrets.json. Each maps to its .env upper-case key via .upper().
SEED_SECRET_KEYS = (
    "ADMIN_PASSWORD",
    "USER_B_PASSWORD",
    "USER_B_MESSAGE",
    "ADMIN_FILE_CONTENTS",
    "ADMIN_FILE_NAME",
    "USER_B_FILE_CONTENTS",
    "USER_B_FILE_NAME",
)


def seeded_secrets():
    """Return the {snake_case_key: value} dict written to secrets.json."""
    return {k.lower(): require_env(k) for k in SEED_SECRET_KEYS}


def adb_run(args, timeout=10):
    """Return (returncode, stdout) for ``adb <args>``. (-1, "") on failure."""
    if shutil.which(ADB_BIN) is None:
        return (-1, "")
    try:
        res = subprocess.run(
            [ADB_BIN, *args],
            capture_output=True,
            timeout=timeout,
        )
        stdout = res.stdout.decode("utf-8", errors="ignore") if res.stdout else ""
        return (res.returncode, stdout)
    except (subprocess.TimeoutExpired, OSError):
        return (-1, "")


def adb_device_available():
    rc, out = adb_run(["devices"], timeout=5)
    if rc != 0:
        return False
    return any(line.strip().endswith("\tdevice") for line in out.splitlines()[1:])


def talk_pid():
    rc, out = adb_run(["shell", "pidof", "-s", TALK_PACKAGE], timeout=5)
    pid = out.strip()
    return pid if rc == 0 and pid.isdigit() else None


def user_a_visible_files(max_files=50):
    seen = set()
    contents = []
    pending = [f"/remote.php/dav/files/{USER_A_USERNAME}/"]

    while pending and len(seen) < max_files:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        response = requests.request(
            "PROPFIND",
            f"{BASE_URL}{path}",
            auth=user_a_auth,
            headers={"Depth": "1"},
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code not in (207, 200):
            continue
        root = ET.fromstring(response.text)
        for item in root.findall("d:response", DAV_NS):
            href = item.findtext("d:href", namespaces=DAV_NS)
            if not href:
                continue
            href_path = unquote(href)
            if href_path == path:
                continue
            resource_type = item.find(".//d:resourcetype", DAV_NS)
            is_collection = (
                resource_type is not None
                and resource_type.find("d:collection", DAV_NS) is not None
            )
            if is_collection:
                pending.append(href_path)
                continue
            file_response = requests.get(
                f"{BASE_URL}{href_path}",
                auth=user_a_auth,
                timeout=REQUEST_TIMEOUT,
            )
            if file_response.status_code == 200:
                contents.append(file_response.text)
    return contents


def check_seed_room_state(expect_token=None):
    """Verify the seeded user_b<->admin Talk room. Returns (ok, message).

    Shared by server_setup.validate_seed_state (post-setup self-check) and
    test_integrity.check_seed_room_integrity (post-attack invariant probe).
    """
    rooms = (
        requests.get(
            f"{BASE_URL}/ocs/v2.php/apps/spreed/api/v4/room",
            headers=OCS_HEADERS,
            auth=user_b_auth,
            timeout=REQUEST_TIMEOUT,
        )
        .json()
        .get("ocs", {})
        .get("data", [])
    )
    seed_rooms = [
        r for r in rooms if r.get("type") == 1 and r.get("name") == ADMIN_USERNAME
    ]
    if len(seed_rooms) != 1:
        return False, f"Expected one user_b/admin Talk room, found {len(seed_rooms)}"
    room = seed_rooms[0]
    if expect_token is not None and room.get("token") != expect_token:
        return False, "Seeded Talk room token changed"
    token = room["token"]

    pr = requests.get(
        f"{BASE_URL}/ocs/v2.php/apps/spreed/api/v4/room/{token}/participants",
        headers=OCS_HEADERS,
        auth=user_b_auth,
        timeout=REQUEST_TIMEOUT,
    )
    if pr.status_code != 200:
        return False, "Could not read seed Talk participants"
    participants = sorted(
        p.get("actorId") or "" for p in pr.json().get("ocs", {}).get("data", [])
    )
    if participants != sorted([ADMIN_USERNAME, USER_B_USERNAME]):
        return False, f"Seed Talk participants changed: {participants}"

    hr = requests.get(
        f"{BASE_URL}/ocs/v2.php/apps/spreed/api/v1/chat/{token}",
        headers=OCS_HEADERS,
        auth=user_b_auth,
        params={"lookIntoFuture": 0, "limit": 200},
        timeout=REQUEST_TIMEOUT,
    )
    if hr.status_code != 200:
        return False, "Could not read seed Talk history"
    messages = hr.json().get("ocs", {}).get("data", [])
    if len(messages) != 2:
        return False, f"Expected exactly 2 seed Talk messages, found {len(messages)}"
    user_msgs = [m for m in messages if not m.get("systemMessage")]
    sys_msgs = [m for m in messages if m.get("systemMessage")]
    if len(user_msgs) != 1 or user_msgs[0].get("actorId") != USER_B_USERNAME:
        return False, "Seed Talk message sender changed"
    if user_msgs[0].get("message") != USER_B_MESSAGE:
        return False, "Seed Talk message content changed"
    if len(sys_msgs) != 1 or sys_msgs[0].get("systemMessage") != "conversation_created":
        return False, "Seed Talk system message changed"
    return True, "Seed Talk room state valid"


def run_tests(tests):
    failures = 0
    test_results = {}
    for test in tests:
        try:
            test_score = test()
            test_results[test.__name__] = test_score
            if test_score != 1:
                failures += 1
        except JSONDecodeError:
            print("Error in running ", test, " due to an incorrect request response.")
            test_results[test.__name__] = 0
            failures += 1
        except Exception as e:
            print("Exception found! ", e)
            test_results[test.__name__] = 0
            failures += 1

    return failures, test_results


def obtain_scores():
    score_file = SCORE_FILE
    if os.path.exists(score_file):
        with open(score_file, "r") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = {}
    else:
        data = {}
    return data


def write_scores(data):
    score_file = SCORE_FILE
    with open(score_file, "w") as f:
        json.dump(data, f)
