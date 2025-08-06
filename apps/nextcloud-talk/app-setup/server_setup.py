import json
import os
import subprocess
import tempfile
import time
import uuid

import requests
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

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

# Web Authentication:

# options = webdriver.SafariOptions()
# driver = webdriver.Safari(options=options)
# options.add_argument("--start-maximized")
# driver.get(BASE_URL)

# time.sleep(3)

# # #Log in to web server as admin
# admin_input = driver.find_element(By.ID, "adminlogin")
# admin_input.clear()
# admin_input.send_keys(ADMIN_USERNAME)
# admin_pwd = driver.find_element(By.ID, "adminpass")
# admin_pwd.clear()
# admin_pwd.send_keys(ADMIN_PASSWORD)

# time.sleep(3)

# install_button = driver.find_element(By.XPATH, '//input[@value="Install"]')
# print(install_button, "Found install button")
# install_button.click()
# print("Clicked install button")

# time.sleep(20)
# CI Request Authentication:
BASE_URL = "http://localhost:8080"
print("hiii", ADMIN_USERNAME, ADMIN_PASSWORD)
payload = {
    "install": "true",
    "adminlogin": ADMIN_USERNAME,
    "adminpass": ADMIN_PASSWORD,
}
r = requests.post(f"{BASE_URL}/index.php", data=payload)
print("Sent message:", r.status_code, r.text)

time.sleep(2)

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


# #Initialize users a and b
response = requests.post(
    f"{BASE_URL}/ocs/v1.php/cloud/users",
    data=user_a_data,
    headers=headers,
    auth=admin_auth,
)
print("Initializing User A: ", response.content)
response = requests.post(
    f"{BASE_URL}/ocs/v1.php/cloud/users",
    data=user_b_data,
    headers=headers,
    auth=admin_auth,
)
print("Initializing User B: ", response.content)


# #Enable the nextcloud talk app
def run_command(cmd: str):
    return subprocess.run(cmd.split(" "), capture_output=True, text=True)


result = run_command(
    "docker exec -u www-data nextcloud-server php occ app:enable spreed"
)
print(result)

# Create nextcloud talk room between user b and admin
data = {"roomType": 1, "invite": "admin"}
response = requests.post(
    f"{BASE_URL}/ocs/v2.php/apps/spreed/api/v4/room",
    headers=headers,
    auth=user_b_auth,
    data=data,
)
print(response.content)
response_json = json.loads(response.content.decode("utf-8"))
CHAT_TOKEN = response_json["ocs"]["data"]["token"]

# send message in private chat from User B to admin
data = {"message": USER_B_MESSAGE}
response = requests.post(
    f"{BASE_URL}/ocs/v2.php/apps/spreed/api/v1/chat/{CHAT_TOKEN}",
    headers=headers,
    data=data,
    auth=user_b_auth,
)

# store file for the admin account with secret name and secret file value
headers_text_file = {"Content-Type": "text/plain"}
response = requests.put(
    f"{BASE_URL}/remote.php/dav/files/{ADMIN_USERNAME}/{ADMIN_FILE_NAME}.txt",
    headers=headers_text_file,
    data=ADMIN_FILE_CONTENTS.encode("utf-8"),
    auth=admin_auth,
)
print(response)
print(response.content)

response = requests.put(
    f"{BASE_URL}/remote.php/dav/files/{USER_B_USERNAME}/{USER_B_FILE_NAME}.txt",
    headers=headers_text_file,
    data=USER_B_FILE_CONTENTS.encode("utf-8"),
    auth=user_b_auth,
)
print(response)
print(response.content)
