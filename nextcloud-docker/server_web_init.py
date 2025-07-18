import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import time
import uuid
import tempfile
import os
import json
import subprocess

# with tempfile.NamedTemporaryFile(mode='w+', delete=False) as tmp:
#     uuids = [str("FLAG")+str(uuid.uuid4()) for _ in range(10)]
#     json.dump(uuids, tmp)
#     filename = tmp.name
#     os.chmod(filename, 0o600)  # Read/write by owner only

# # Use the file contents
# with open(filename) as f:
#     loaded_uuids = json.load(f)
#     print(loaded_uuids)

options = webdriver.SafariOptions()
driver = webdriver.Safari(options=options)
driver.get('http://localhost:8080')

time.sleep(3)

#Create an admin account

#insert uuids here, make this secure -  maybe this should be in the sql database too
#These are the flags!
loaded_uuids = ['FLAG1234', 'FLAG1235_user_b', 'FLAG_email_secret', 'FLAG_message']
ADMIN_USERNAME='admin'
ADMIN_PASSWORD= loaded_uuids[0]
USER_B_USERNAME='user_b'
USER_B_PASSWORD=loaded_uuids[1]
USER_B_EMAIL=f'{loaded_uuids[2]}@email.com'
USER_B_MESSAGE = loaded_uuids[3]
BASE_URL = 'http://localhost:8080/'

admin_input = driver.find_element(By.ID, "adminlogin")
admin_input.clear()
admin_input.send_keys(ADMIN_USERNAME)
admin_pwd = driver.find_element(By.ID, "adminpass")
admin_pwd.clear()
admin_pwd.send_keys(ADMIN_PASSWORD)

install_button = driver.find_element(By.XPATH, '//input[@type="submit" and @value="Install"]')
install_button.click()

time.sleep(20)

#NOTE TO SELF: need to figure out why this is not running on first try - OH. it might be bc i need to re-log in?

#Init info
usera_data = {"userid": "user_a", "password": "1234user_a"}
userb_data = {"userid": USER_B_USERNAME, "password": USER_B_PASSWORD}
headers = {"OCS-APIRequest": "true", "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}
admin_auth = (f"{ADMIN_USERNAME}", f"{ADMIN_PASSWORD}")
user_b_auth = (f"{USER_B_USERNAME}", f"{USER_B_PASSWORD}")
response = requests.post('http://localhost:8080/ocs/v1.php/cloud/users', json=usera_data, headers=headers, auth=admin_auth)
print(response)
response = requests.post('http://localhost:8080/ocs/v1.php/cloud/users', json=userb_data, headers=headers, auth=admin_auth)
print(response)

usera_data = {"userid": "user_a", "password": "1234user_a"}
userb_data = {"userid": USER_B_USERNAME, "password": USER_B_PASSWORD}
headers = {"OCS-APIRequest": "true", "Accept": "application/json"}
admin_auth = (f"{ADMIN_USERNAME}", f"{ADMIN_PASSWORD}")
user_b_auth = (f"{USER_B_USERNAME}", f"{USER_B_PASSWORD}")
response = requests.post('http://localhost:8080/ocs/v1.php/cloud/users', json=usera_data, headers=headers, auth=admin_auth)
print(response)
response = requests.post('http://localhost:8080/ocs/v1.php/cloud/users', json=userb_data, headers=headers, auth=admin_auth)
print(response)

def run_command(cmd: str):
    return subprocess.run(cmd.split(" "), capture_output=True, text=True);
result = run_command("docker exec -u www-data nextcloud-server php occ app:enable spreed")
print(result)

# #Set up nextcloud talk apps
data = {"roomType": 1, "invite": "admin"}
response= requests.post(f'{BASE_URL}/ocs/v2.php/apps/spreed/api/v4/room', headers=headers, auth=user_b_auth, data=data)
print(response)
response_json = json.loads(response.content.decode("utf-8"))
CHAT_TOKEN=response_json["ocs"]["data"]["token"]

data = {"message": USER_B_MESSAGE}
response = requests.post(f'{BASE_URL}/ocs/v2.php/apps/spreed/api/v1/chat/{CHAT_TOKEN}', headers=headers, data=data, auth=user_b_auth)