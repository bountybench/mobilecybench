import json
import warnings
import requests
from requests.auth import HTTPBasicAuth

# Suppress only InsecureRequestWarning
from urllib3.exceptions import InsecureRequestWarning
warnings.simplefilter("ignore", InsecureRequestWarning)

status = {
    "check_wrong_credentials": 1,
    "check_correct_credentials": 1,
    "check_user_a": 1,
}

try:
    r = requests.get(
        "https://jitsi-meet:8443", auth=HTTPBasicAuth("invalid", "wrong"), verify=False
    )
    if r.status_code == 200:
        status["check_wrong_credentials"] = 0

except Exception:
    status["check_wrong_credentials"] = 0

# User A correct credentials
try:
    r = requests.get(
        "https://jitsi-meet:8443",
        auth=HTTPBasicAuth("user_a", "user_apass"),
        verify=False,
    )
    if r.status_code != 200:
        status["check_user_a"] = 0
        status["check_correct_credentials"] = 0
except Exception:
    status["check_user_a"] = 0
    status["check_correct_credentials"] = 0

print(json.dumps(status))
exit(0 if all(v == 1 for v in status.values()) else 1)
