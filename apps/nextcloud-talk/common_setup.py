import json
import os
from pathlib import Path

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


# Load env variables
ADMIN_USER = os.getenv("ADMIN_USERNAME")
ADMIN_PASS = os.getenv("ADMIN_PASSWORD")
USER_B = os.getenv("USER_B_USERNAME")
USER_B_PASS = os.getenv("USER_B_PASSWORD")
USER_B_EMAIL = os.getenv("USER_B_EMAIL")
USER_B_MSG = os.getenv("USER_B_MESSAGE")
USER_A = os.getenv("USER_A_USERNAME")
USER_A_PASS = os.getenv("USER_A_PASSWORD")
ADMIN_FILE_CONTENTS = os.getenv("ADMIN_LOCAL_FILE")
ADMIN_FILE_NAME = os.getenv("ADMIN_FILE_NAME")
USER_B_FILE_CONTENTS = os.getenv("USER_B_LOCAL_FILE")
USER_B_FILE_NAME = os.getenv("USER_B_FILE_NAME")

BASE_URL = get_host_base_url()
ensure_requests_ca_bundle(BASE_URL)
OCS_HEADERS = {
    "OCS-APIRequest": "true",
    "Accept": "application/json",
    "Content-Type": "application/json",
}
admin_auth = (ADMIN_USER, ADMIN_PASS)
user_b_auth = (USER_B, USER_B_PASS)
user_a_auth = (USER_A, USER_A_PASS)

SCORE_FILE = "scores.json"


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
