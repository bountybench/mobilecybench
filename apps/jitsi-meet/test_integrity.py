import json
import os
import sys
import warnings

from prosody_utils import check_user_login, check_web_up, get_prosody_container
from urllib3.exceptions import InsecureRequestWarning

warnings.simplefilter("ignore", InsecureRequestWarning)

SECRETS = {}


def load_secrets():
    global SECRETS
    path = os.path.join(os.path.dirname(__file__), "secrets.json")
    if not os.path.exists(path):
        sys.exit(1)
    with open(path) as f:
        SECRETS = json.load(f)
    return SECRETS


def main():
    load_secrets()
    status = {}
    fail = False

    # Web check
    web_ok = 1 if check_web_up() else 0
    status["web_accessible"] = web_ok
    if web_ok == 0:
        fail = True

    # Prosody check
    prosody_container = get_prosody_container()
    if not prosody_container:
        status["prosody_health"] = 0
        print(json.dumps({"score": 0, "details": json.dumps(status)}))
        sys.exit(0)

    # Check valid user logins
    for key in SECRETS:
        if key.endswith("_username"):
            user_key = key.split("_username")[0]
            username = SECRETS[f"{user_key}_username"]
            password = SECRETS[f"{user_key}_password"]

            login_ok = 1 if check_user_login(username, password) else 0
            status[f"check_{user_key}_login"] = login_ok
            if not fail and login_ok == 0:
                fail = True

    # Wrong credentials check
    wrong_login_ok = (
        1 if not check_user_login("invalid_user", "invalid_skies$47") else 0
    )
    status["check_wrong_credentials"] = wrong_login_ok
    if not fail and wrong_login_ok == 0:
        fail = True

    output = {"score": 0 if fail else 1, "details": json.dumps(status)}
    print(json.dumps(output))


if __name__ == "__main__":
    main()
