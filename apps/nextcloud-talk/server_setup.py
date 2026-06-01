import json
import subprocess
import time
from pathlib import Path

import requests
from common_setup import (
    ADMIN_FILE_CONTENTS,
    ADMIN_FILE_NAME,
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    BASE_URL,
    REQUEST_TIMEOUT,
    USER_A_PASSWORD,
    USER_A_USERNAME,
    USER_B_EMAIL,
    USER_B_FILE_CONTENTS,
    USER_B_FILE_NAME,
    USER_B_MESSAGE,
    USER_B_PASSWORD,
    USER_B_USERNAME,
    admin_auth,
    check_seed_room_state,
    get_trusted_domain,
    require_env,
    seeded_secrets,
    user_b_auth,
)

MYSQL_USER = require_env("MYSQL_USER")
MYSQL_PASSWORD = require_env("MYSQL_PASSWORD")
MYSQL_DATABASE = require_env("MYSQL_DATABASE")

script_dir = Path(__file__).parent
secrets_file = script_dir / "secrets.json"
SPREED_ROOM_URL = f"{BASE_URL}/ocs/v2.php/apps/spreed/api/v4/room"

with open(secrets_file, "w") as f:
    json.dump(seeded_secrets(), f, indent=2)
print("Synced secrets from benchmark.env to secrets.json")


def wait_for_server(max_retries=10, delay=10):
    """Wait for Nextcloud server to be ready"""
    for attempt in range(max_retries):
        try:
            response = requests.get(f"{BASE_URL}/status.php", timeout=5)
            if response.status_code == 200:
                print(f"Server is ready after {attempt + 1} attempts")
                return True
        except requests.exceptions.RequestException:
            pass

        if attempt < max_retries - 1:
            print(f"Waiting for server... (attempt {attempt + 1}/{max_retries})")
            time.sleep(delay)

    print("Server failed to become ready")
    return False


if not wait_for_server():
    print("ERROR: Nextcloud server is not ready")
    exit(1)

payload = {
    "install": "true",
    "adminlogin": ADMIN_USERNAME,
    "adminpass": ADMIN_PASSWORD,
}


def run_command(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def fail(message):
    print(f"ERROR: {message}")
    exit(1)


def ocs_meta_ok(response, expected=(100, 200, 201)):
    try:
        meta = response.json().get("ocs", {}).get("meta", {})
    except ValueError:
        return False
    return response.status_code in (200, 201) and meta.get("statuscode") in expected


def ocs_data(response):
    return response.json().get("ocs", {}).get("data")


def initialize_nextcloud(max_retries=5):
    """Initialize Nextcloud with retry logic"""
    for attempt in range(max_retries):
        try:
            r = requests.post(
                f"{BASE_URL}/index.php",
                data=payload,
                timeout=30,
                allow_redirects=False,
            )
            print("Sent message:", r.status_code, r.text[:200])
            if r.status_code in [200, 302, 303]:
                return True
        except requests.exceptions.RequestException as e:
            print(f"Initialization attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(5)

    print("ERROR: Failed to initialize Nextcloud")
    exit(1)


initialize_nextcloud()

time.sleep(10)  # Wait longer for Nextcloud to be fully ready


def configure_https_runtime():
    trusted_domain = get_trusted_domain()
    php_script = f"""
include "/var/www/html/config/config.php";
if (!isset($CONFIG["trusted_domains"])) {{
    $CONFIG["trusted_domains"] = array();
}} elseif (!is_array($CONFIG["trusted_domains"])) {{
    $CONFIG["trusted_domains"] = array($CONFIG["trusted_domains"]);
}}
if (!in_array({json.dumps(trusted_domain)}, $CONFIG["trusted_domains"], true)) {{
    $CONFIG["trusted_domains"][] = {json.dumps(trusted_domain)};
}}
$CONFIG["overwriteprotocol"] = "https";
$CONFIG["overwrite.cli.url"] = {json.dumps(BASE_URL)};
$config_content = "<?php\\n\\$CONFIG = " . var_export($CONFIG, true) . ";\\n";
file_put_contents("/var/www/html/config/config.php", $config_content);
"""
    result = run_command(
        [
            "docker",
            "exec",
            "-u",
            "root",
            "nextcloud-server",
            "php",
            "-r",
            php_script,
        ]
    )
    if result.returncode != 0:
        print("ERROR: Failed to configure Nextcloud HTTPS settings")
        print(result.stderr)
        exit(1)


configure_https_runtime()

# #Initialize data
headers = {
    "OCS-APIRequest": "true",
    "Accept": "application/json",
    "Content-Type": "application/x-www-form-urlencoded",
}
user_a_data = {"userid": USER_A_USERNAME, "password": USER_A_PASSWORD}
user_b_data = {
    "userid": USER_B_USERNAME,
    "password": USER_B_PASSWORD,
    "email": USER_B_EMAIL,
}


# #Initialize users a and b with retry logic
def create_user_with_retry(user_data, user_name, max_retries=3):
    # First check if user already exists
    userid = user_data["userid"]
    check_response = requests.get(
        f"{BASE_URL}/ocs/v1.php/cloud/users/{userid}",
        headers=headers,
        auth=admin_auth,
        timeout=REQUEST_TIMEOUT,
    )

    if check_response.status_code == 200:
        try:
            response_json = check_response.json()
            if response_json.get("ocs", {}).get("meta", {}).get("statuscode") == 100:
                print(f"{user_name} already exists, skipping creation")
                return check_response
        except Exception:
            pass

    # User doesn't exist, create it
    for attempt in range(max_retries):
        response = requests.post(
            f"{BASE_URL}/ocs/v1.php/cloud/users",
            data=user_data,
            headers=headers,
            auth=admin_auth,
            timeout=REQUEST_TIMEOUT,
        )
        print(f"Initializing {user_name} (attempt {attempt + 1}): ", response.content)

        if response.status_code == 200 and "failure" not in response.content.decode(
            "utf-8"
        ):
            print(f"{user_name} created successfully")
            return response
        elif attempt < max_retries - 1:
            print(f"Retrying {user_name} creation in 10 seconds...")
            time.sleep(10)  # Increased delay

    raise RuntimeError(f"Failed to create {user_name} after {max_retries} attempts")


create_user_with_retry(user_a_data, "User A")
time.sleep(2)
create_user_with_retry(user_b_data, "User B")
time.sleep(2)

# Email must be set via a separate PUT — the creation endpoint ignores it
if USER_B_EMAIL:
    r = requests.put(
        f"{BASE_URL}/ocs/v1.php/cloud/users/{USER_B_USERNAME}",
        headers=headers,
        auth=admin_auth,
        data={"key": "email", "value": USER_B_EMAIL},
        timeout=REQUEST_TIMEOUT,
    )
    print(f"Set user_b email: {r.status_code}")


# #Enable the nextcloud talk app
result = run_command(
    [
        "docker",
        "exec",
        "-u",
        "www-data",
        "nextcloud-server",
        "php",
        "occ",
        "app:enable",
        "spreed",
    ]
)
print(result)


def wait_for_spreed(max_retries=20, delay=2):
    for attempt in range(max_retries):
        try:
            response = requests.get(
                SPREED_ROOM_URL,
                headers=headers,
                auth=user_b_auth,
                timeout=REQUEST_TIMEOUT,
            )
            if ocs_meta_ok(response, expected=(200,)):
                print(f"Spreed API is ready after {attempt + 1} attempts")
                return
        except requests.exceptions.RequestException:
            pass
        if attempt < max_retries - 1:
            time.sleep(delay)
    fail("Spreed API did not become ready")


def list_user_b_rooms():
    response = requests.get(
        SPREED_ROOM_URL,
        headers=headers,
        auth=user_b_auth,
        timeout=REQUEST_TIMEOUT,
    )
    if not ocs_meta_ok(response, expected=(200,)):
        fail("Failed to list user_b Talk rooms")
    return ocs_data(response)


def is_seed_room(room):
    return room.get("type") == 1 and room.get("name") == ADMIN_USERNAME


def run_sql(sql):
    result = run_command(
        [
            "docker",
            "exec",
            "nextcloud-database",
            "mariadb",
            f"-u{MYSQL_USER}",
            f"-p{MYSQL_PASSWORD}",
            MYSQL_DATABASE,
            "-e",
            sql,
        ]
    )
    if result.returncode != 0:
        print(result.stderr)
        fail("Failed to update Nextcloud database")


def delete_room(room):
    room_id = int(room["id"])
    token = room["token"]
    # One-to-one Talk rooms cannot be deleted through public API/OCC in this version.
    run_sql(
        f"""
        DELETE FROM oc_comments_read_markers WHERE object_type = 'chat' AND object_id = '{room_id}';
        DELETE FROM oc_comments WHERE object_type = 'chat' AND object_id = '{room_id}';
        DELETE FROM oc_talk_thread_attendees WHERE room_id = {room_id};
        DELETE FROM oc_talk_threads WHERE room_id = {room_id};
        DELETE FROM oc_talk_sessions WHERE attendee_id IN (SELECT id FROM oc_talk_attendees WHERE room_id = {room_id});
        DELETE FROM oc_talk_attendees WHERE room_id = {room_id};
        DELETE FROM oc_talk_rooms WHERE id = {room_id};
        """
    )
    print(f"Deleted existing seeded Talk room token={token}")


def reset_seed_room():
    for room in list_user_b_rooms():
        if is_seed_room(room):
            delete_room(room)


def create_chat_room(max_retries=5):
    data = {"roomType": 1, "invite": ADMIN_USERNAME}

    for attempt in range(max_retries):
        try:
            response = requests.post(
                SPREED_ROOM_URL,
                headers=headers,
                auth=user_b_auth,
                data=data,
                timeout=REQUEST_TIMEOUT,
            )
            if ocs_meta_ok(response, expected=(200, 201)):
                token = ocs_data(response)["token"]
                print(f"Chat room created successfully with token: {token}")
                return token
        except (KeyError, requests.exceptions.RequestException) as e:
            print(f"Chat room creation failed (attempt {attempt + 1}): {e}")

        if attempt < max_retries - 1:
            time.sleep(2)
    fail("Failed to create chat room after all attempts")


def send_seed_message(chat_token, max_retries=3):
    data = {"message": USER_B_MESSAGE}

    for attempt in range(max_retries):
        try:
            response = requests.post(
                f"{BASE_URL}/ocs/v2.php/apps/spreed/api/v1/chat/{chat_token}",
                headers=headers,
                data=data,
                auth=user_b_auth,
                timeout=REQUEST_TIMEOUT,
            )
            if ocs_meta_ok(response, expected=(201,)):
                print("Seed Talk message sent")
                return
        except requests.exceptions.RequestException as e:
            print(f"Message send failed (attempt {attempt + 1}): {e}")
        if attempt < max_retries - 1:
            time.sleep(2)
    fail("Failed to send seed Talk message")


wait_for_spreed()
reset_seed_room()
CHAT_TOKEN = create_chat_room()
send_seed_message(CHAT_TOKEN)


# store file for the admin account with secret name and secret file value
def upload_file_with_retry(url, content, auth, max_retries=3):
    """Upload file with retry logic"""
    headers_text_file = {"Content-Type": "text/plain"}

    for attempt in range(max_retries):
        try:
            response = requests.put(
                url,
                headers=headers_text_file,
                data=content.encode("utf-8"),
                auth=auth,
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code in [200, 201, 204]:
                return response
        except requests.exceptions.RequestException as e:
            print(f"File upload failed (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2)

    print(f"WARNING: Failed to upload file to {url} after all attempts")
    return None


admin_file_response = upload_file_with_retry(
    f"{BASE_URL}/remote.php/dav/files/{ADMIN_USERNAME}/{ADMIN_FILE_NAME}.txt",
    ADMIN_FILE_CONTENTS,
    admin_auth,
)
if admin_file_response:
    print("Admin file uploaded:", admin_file_response.status_code)

user_b_file_response = upload_file_with_retry(
    f"{BASE_URL}/remote.php/dav/files/{USER_B_USERNAME}/{USER_B_FILE_NAME}.txt",
    USER_B_FILE_CONTENTS,
    user_b_auth,
)
if user_b_file_response:
    print("User B file uploaded:", user_b_file_response.status_code)


def validate_user_b_email():
    response = requests.get(
        f"{BASE_URL}/ocs/v1.php/cloud/users/{USER_B_USERNAME}",
        headers=headers,
        auth=user_b_auth,
        timeout=REQUEST_TIMEOUT,
    )
    if not ocs_meta_ok(response):
        fail("Failed to read user_b profile")
    actual = ocs_data(response).get("email", "")
    if actual.lower() != USER_B_EMAIL.lower():
        fail("user_b email validation failed")


def validate_file(path, expected, auth, label):
    response = requests.get(path, auth=auth, timeout=REQUEST_TIMEOUT)
    if response.status_code != 200:
        fail(f"{label} file validation failed: missing")
    if response.text != expected:
        fail(f"{label} file validation failed: content mismatch")


def validate_seed_state():
    validate_user_b_email()
    ok, msg = check_seed_room_state(expect_token=CHAT_TOKEN)
    if not ok:
        fail(msg)
    validate_file(
        f"{BASE_URL}/remote.php/dav/files/{ADMIN_USERNAME}/{ADMIN_FILE_NAME}.txt",
        ADMIN_FILE_CONTENTS,
        admin_auth,
        "admin",
    )
    validate_file(
        f"{BASE_URL}/remote.php/dav/files/{USER_B_USERNAME}/{USER_B_FILE_NAME}.txt",
        USER_B_FILE_CONTENTS,
        user_b_auth,
        "user_b",
    )
    print("Seed state validation passed")


validate_seed_state()
