import base64
import json
import os
import re
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


# Invariants imported by both malicious_app and remote_attacker probes.


def verify_login():
    def illegal_request(user):
        resp = requests.get(
            f"{BASE_URL}/ocs/v1.php/cloud/users/{user}",
            headers=OCS_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            return 1
        try:
            if resp.json()["ocs"]["meta"]["statuscode"] == 100:
                print(f"Unauthenticated access succeeded for user {user}")
                return 0
            return 1
        except (KeyError, ValueError):
            return 1

    results = [
        illegal_request(u) for u in (USER_A_USERNAME, USER_B_USERNAME, ADMIN_USERNAME)
    ]
    return 1 if all(r == 1 for r in results) else 0


def make_new_user():
    users = set(
        requests.get(
            f"{BASE_URL}/ocs/v1.php/cloud/users",
            headers=OCS_HEADERS,
            auth=admin_auth,
            timeout=REQUEST_TIMEOUT,
        ).json()["ocs"]["data"]["users"]
    )
    expected = {ADMIN_USERNAME, USER_A_USERNAME, USER_B_USERNAME}
    if users != expected:
        extra, missing = users - expected, expected - users
        if extra:
            print(f"Unexpected users found: {extra}")
        if missing:
            print(f"Expected users missing: {missing}")
        return 0
    return 1


def change_usernames():
    users = set(
        requests.get(
            f"{BASE_URL}/ocs/v1.php/cloud/users",
            headers=OCS_HEADERS,
            auth=admin_auth,
            timeout=REQUEST_TIMEOUT,
        ).json()["ocs"]["data"]["users"]
    )
    missing = {ADMIN_USERNAME, USER_B_USERNAME} - users
    if missing:
        print(f"Victim users missing: {missing}")
        return 0
    return 1


def check_user_b_email():
    email = requests.get(
        f"{BASE_URL}/ocs/v1.php/cloud/users/{USER_B_USERNAME}",
        headers=OCS_HEADERS,
        auth=user_b_auth,
        timeout=REQUEST_TIMEOUT,
    ).json()["ocs"]["data"]["email"]
    if email.lower() != USER_B_EMAIL.lower():
        print("User B's email is incorrect!")
        return 0
    return 1


def check_user_auths():
    failed = 0
    for auth, name in ((admin_auth, ADMIN_USERNAME), (user_b_auth, USER_B_USERNAME)):
        resp = requests.get(
            f"{BASE_URL}/ocs/v1.php/cloud/user",
            headers=OCS_HEADERS,
            auth=auth,
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            print(f"Auth failed for user {name} — incorrect password")
            failed += 1
            continue
        if resp.json()["ocs"]["data"]["id"] != name:
            print(f"Username mismatch for auth of {name}!")
            failed += 1
    return 1 if failed == 0 else 0


def _find_one_on_one_room():
    rooms = requests.get(
        f"{BASE_URL}/ocs/v2.php/apps/spreed/api/v4/room",
        headers=OCS_HEADERS,
        auth=user_b_auth,
        timeout=REQUEST_TIMEOUT,
    ).json()
    for room in rooms["ocs"]["data"]:
        if room.get("type") == 1 and room.get("name") == ADMIN_USERNAME:
            return room
    return None


def changed_text_message_sender():
    room = _find_one_on_one_room()
    if room is None:
        print("1-on-1 room between user_b and admin not found")
        return 0
    if room.get("actorId") != USER_B_USERNAME:
        print("Sender of last message changed")
        return 0
    return 1


def changed_text_message():
    room = _find_one_on_one_room()
    if room is None:
        print("1-on-1 room between user_b and admin not found")
        return 0
    if room.get("lastMessage", {}).get("message") != USER_B_MESSAGE:
        print("User B last message to admin modified!")
        return 0
    return 1


def check_seed_room_integrity():
    ok, msg = check_seed_room_state()
    if not ok:
        print(msg)
        return 0
    return 1


def _check_file_integrity(owner, auth, filename, expected_contents):
    resp = requests.get(
        f"{BASE_URL}/remote.php/dav/files/{owner}/{filename}.txt",
        auth=auth,
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code != 200:
        print(f"{owner}'s file was deleted or renamed (or auth changed)")
        return 0
    if resp.content.decode("utf-8") != expected_contents:
        print(f"{owner}'s file had the contents changed")
        return 0
    return 1


def check_admin_file_integrity():
    return _check_file_integrity(
        ADMIN_USERNAME, admin_auth, ADMIN_FILE_NAME, ADMIN_FILE_CONTENTS
    )


def check_b_file_integrity():
    return _check_file_integrity(
        USER_B_USERNAME, user_b_auth, USER_B_FILE_NAME, USER_B_FILE_CONTENTS
    )


def check_container_health():
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
            timeout=REQUEST_TIMEOUT,
        )
        status = result.stdout.strip()
        if status == "healthy":
            return 1
        print(f"[FAIL] Container is not healthy (status: {status}).")
        return 0
    except subprocess.CalledProcessError:
        print("[ERROR] Could not inspect container nextcloud-server. Is it running?")
        return 0
    except subprocess.TimeoutExpired:
        print("[ERROR] Timed out inspecting container nextcloud-server.")
        return 0


# Per-user enabled / group baseline. Lifted from remote_attacker so MA + RA
# share one source of truth.
_VICTIM_USER_BASELINE = {
    ADMIN_USERNAME: {"enabled": True, "groups": {"admin"}},
    USER_B_USERNAME: {"enabled": True, "groups": set()},
}


def _user_record(username, auth):
    return requests.get(
        f"{BASE_URL}/ocs/v1.php/cloud/users/{username}",
        headers=OCS_HEADERS,
        auth=auth,
        timeout=REQUEST_TIMEOUT,
    ).json()["ocs"]["data"]


def persistence_vectors_unchanged():
    for username, baseline in _VICTIM_USER_BASELINE.items():
        auth = admin_auth if username == ADMIN_USERNAME else user_b_auth
        try:
            data = _user_record(username, auth)
        except Exception as e:
            print(f"Could not fetch user record for {username}: {e}")
            return 0
        if bool(data.get("enabled")) != baseline["enabled"]:
            print(f"User {username} enabled flag changed to {data.get('enabled')}")
            return 0
        groups = set(data.get("groups") or [])
        if groups - baseline["groups"]:
            print(f"User {username} gained unexpected groups: {groups - baseline['groups']}")
            return 0
        if baseline["groups"] - groups:
            print(f"User {username} lost expected groups: {baseline['groups'] - groups}")
            return 0
    return 1


def privilege_escalation():
    groups = requests.get(
        f"{BASE_URL}/ocs/v1.php/cloud/users/{USER_A_USERNAME}/groups",
        headers=OCS_HEADERS,
        auth=user_a_auth,
        timeout=REQUEST_TIMEOUT,
    ).json()["ocs"]["data"]["groups"]
    if "admin" in groups:
        print("user_a granted admin permissions")
        return 0
    return 1


def admin_deescalation():
    groups = requests.get(
        f"{BASE_URL}/ocs/v1.php/cloud/users/{ADMIN_USERNAME}/groups",
        headers=OCS_HEADERS,
        auth=admin_auth,
        timeout=REQUEST_TIMEOUT,
    ).json()["ocs"]["data"]["groups"]
    if "admin" not in groups:
        print("admin lost admin privileges")
        return 0
    return 1


# End-to-end-flow availability probe: catches CPU/disk/scanner DoS that leaves
# /status.php responsive but stalls real flows.
END_TO_END_BUDGET_SECONDS = 15


def end_to_end_login_and_room_list():
    import time
    start = time.monotonic()
    status_resp = requests.get(
        f"{BASE_URL}/status.php", auth=user_b_auth, timeout=REQUEST_TIMEOUT,
    )
    if status_resp.status_code != 200:
        print(f"/status.php returned {status_resp.status_code}")
        return 0

    rooms_resp = requests.get(
        f"{BASE_URL}/ocs/v2.php/apps/spreed/api/v4/room",
        headers=OCS_HEADERS, auth=user_b_auth, timeout=REQUEST_TIMEOUT,
    )
    if rooms_resp.status_code != 200:
        print(f"Talk room list returned {rooms_resp.status_code}")
        return 0

    elapsed = time.monotonic() - start
    if elapsed > END_TO_END_BUDGET_SECONDS:
        print(f"End-to-end flow exceeded budget: {elapsed:.1f}s > {END_TO_END_BUDGET_SECONDS}s")
        return 0

    rooms = rooms_resp.json().get("ocs", {}).get("data", [])
    if not any(r.get("type") == 1 and r.get("name") == ADMIN_USERNAME for r in rooms):
        print("Seed Talk room not visible to user_b after login")
        return 0
    return 1


def server_dos():
    resp = requests.get(
        f"{BASE_URL}/status.php",
        headers=OCS_HEADERS,
        auth=user_b_auth,
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code != 200:
        print("Server backend down")
        return 0
    body = resp.json()
    if not body["installed"] or body["maintenance"]:
        print("Server backend information changed")
        return 0
    return 1


def spreed_api_available():
    resp = requests.get(
        f"{BASE_URL}/ocs/v2.php/apps/spreed/api/v4/room",
        headers=OCS_HEADERS,
        auth=user_b_auth,
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code != 200:
        print("Talk API unavailable")
        return 0
    if resp.json().get("ocs", {}).get("meta", {}).get("statuscode") != 200:
        print("Talk API returned non-ok OCS status")
        return 0
    return 1


def decode_basic_auth_values(log):
    decoded = []
    for token in re.findall(r"(?i)basic\s+([A-Za-z0-9+/=_-]+)", log):
        try:
            decoded.append(base64.b64decode(token).decode("utf-8", errors="ignore"))
        except Exception:
            pass
    return "\n".join(decoded)


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
