import json
import os
import subprocess
import time

import requests
from dotenv import load_dotenv

# Load initialization variables
load_dotenv()
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
USER_B_USERNAME = os.getenv("USER_B_USERNAME")
USER_B_PASSWORD = os.getenv("USER_B_PASSWORD")
USER_B_EMAIL = os.getenv("USER_B_EMAIL")
USER_B_MESSAGE = os.getenv("USER_B_MESSAGE")
USER_A_USERNAME = os.getenv("USER_A_USERNAME")
USER_A_PASSWORD = os.getenv("USER_A_PASSWORD")
ADMIN_FILE_CONTENTS = os.getenv("ADMIN_LOCAL_FILE")
ADMIN_FILE_NAME = os.getenv("ADMIN_FILE_NAME")
USER_B_FILE_CONTENTS = os.getenv("USER_B_LOCAL_FILE")
USER_B_FILE_NAME = os.getenv("USER_B_FILE_NAME")

BASE_URL = "http://localhost:8080"


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


def initialize_nextcloud(max_retries=5):
    """Initialize Nextcloud with retry logic"""
    for attempt in range(max_retries):
        try:
            r = requests.post(f"{BASE_URL}/index.php", data=payload, timeout=10)
            print("Sent message:", r.status_code, r.text[:200])
            if r.status_code == 200:
                return True
        except requests.exceptions.RequestException as e:
            print(f"Initialization attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(5)

    print("ERROR: Failed to initialize Nextcloud")
    exit(1)


initialize_nextcloud()

time.sleep(10)  # Wait longer for Nextcloud to be fully ready

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
admin_auth = (f"{ADMIN_USERNAME}", f"{ADMIN_PASSWORD}")
user_b_auth = (f"{USER_B_USERNAME}", f"{USER_B_PASSWORD}")


# #Initialize users a and b with retry logic
def create_user_with_retry(user_data, user_name, max_retries=3):
    # First check if user already exists
    userid = user_data["userid"]
    check_response = requests.get(
        f"{BASE_URL}/ocs/v1.php/cloud/users/{userid}",
        headers=headers,
        auth=admin_auth,
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

    return response


create_user_with_retry(user_a_data, "User A")
time.sleep(2)
create_user_with_retry(user_b_data, "User B")
time.sleep(2)


# #Enable the nextcloud talk app
def run_command(cmd: str):
    return subprocess.run(cmd.split(" "), capture_output=True, text=True)


result = run_command(
    "docker exec -u www-data nextcloud-server php occ app:enable spreed"
)
print(result)

# Wait for spreed app to be fully loaded
time.sleep(5)


# Create nextcloud talk room between user b and admin
def create_chat_room(max_retries=5):
    """Create chat room with retry logic"""
    data = {"roomType": 1, "invite": "admin"}

    for attempt in range(max_retries):
        try:
            response = requests.post(
                f"{BASE_URL}/ocs/v2.php/apps/spreed/api/v4/room",
                headers=headers,
                auth=user_b_auth,
                data=data,
                timeout=10,
            )
            print(response.content)

            if response.status_code in [200, 201]:
                response_json = json.loads(response.content.decode("utf-8"))
                if response_json.get("ocs", {}).get("meta", {}).get("status") == "ok":
                    CHAT_TOKEN = response_json["ocs"]["data"]["token"]
                    print(f"Chat room created successfully with token: {CHAT_TOKEN}")
                    return CHAT_TOKEN
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Failed to parse chat room creation response: {e}")
            print("Response content:", response.content.decode("utf-8"))
        except requests.exceptions.RequestException as e:
            print(f"Request failed for chat room creation (attempt {attempt + 1}): {e}")

        if attempt < max_retries - 1:
            print("Retrying chat room creation in 10 seconds...")
            time.sleep(10)

    print("ERROR: Failed to create chat room after all attempts")
    exit(1)


CHAT_TOKEN = create_chat_room()


# send message in private chat from User B to admin
def send_message_with_retry(max_retries=3):
    """Send message with retry logic"""
    data = {"message": USER_B_MESSAGE}

    for attempt in range(max_retries):
        try:
            response = requests.post(
                f"{BASE_URL}/ocs/v2.php/apps/spreed/api/v1/chat/{CHAT_TOKEN}",
                headers=headers,
                data=data,
                auth=user_b_auth,
                timeout=10,
            )
            if response.status_code in [200, 201]:
                return response
        except requests.exceptions.RequestException as e:
            print(f"Message send failed (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2)

    print("WARNING: Failed to send message after all attempts")


send_message_with_retry()


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
                timeout=10,
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
