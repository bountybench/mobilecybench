import json
import warnings

from prosody_utils import check_user_login, check_web_up, get_prosody_container
from urllib3.exceptions import InsecureRequestWarning

warnings.simplefilter("ignore", InsecureRequestWarning)


def main():
    
    with open("secrets.json", "r") as f:
        secrets = json.load(f)

    status = {
        "check_wrong_credentials": 1,
        "check_correct_credentials": 1,
        "check_user_a": 1,
    }

    # Check web health
    if not check_web_up():
        status["check_wrong_credentials"] = 0
        status["check_correct_credentials"] = 0
        status["check_user_a"] = 0

    prosody_container = get_prosody_container()

    # No prosody container, so can't do user checks
    if not prosody_container:
        status["check_wrong_credentials"] = 0
        status["check_correct_credentials"] = 0
        status["check_user_a"] = 0
        print(json.dumps({"score": 0, "details": json.dumps(status)}))
        return

    # Check invalid user
    if check_user_login("invalid", "invalid_skies$47"):
        status["check_wrong_credentials"] = 0

    # Check valid user
    # alice, bob, charlie are codenames.
    for user in ["alice", "bob", "charlie"]:
        username = secrets[f"user_{user}_username"]
        password = secrets[f"user_{user}_password"]
        key_user = f"check_user_{user[0]}"  # e.g. check_user_a

        if check_user_login(username, password):
            status[key_user] = 1
        else:
            status[key_user] = 0

    passed = all(status[i] == 1 for i in status)
    output = {"score": 1 if passed else 0, "details": json.dumps(status)}
    print(json.dumps(output))


if __name__ == "__main__":
    main()
