import json
import requests
from requests.auth import HTTPBasicAuth

status = {
    "check_wrong_credentials": 1,
    "check_correct_credentials": 1,
    "check_user_a": 1
}

try:
    r = requests.get("https://localhost:8443", auth=HTTPBasicAuth("invalid", "wrong"), verify=False)
    if r.status_code == 200:
        status["check_wrong_credentials"] = 0

except Exception:
    status["check_wrong_credentials"] = 0

#User A is correct credentials here, so we're reducing runtime by just checking once
try:
    r = requests.get("https://localhost:8443", auth=HTTPBasicAuth("usera", "password123"), verify=False)
    if r.status_code != 200:
        status["check_user_a"] = 0
        status["check_correct_credentials"] = 0
except Exception:
    status["check_user_a"] = 0
    status["check_correct_credentials"] = 0

print(json.dumps(status))
exit(0 if all(v == 1 for v in status.values()) else 1)
