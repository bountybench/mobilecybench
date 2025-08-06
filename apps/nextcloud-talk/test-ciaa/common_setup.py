import os
from dotenv import load_dotenv
from requests.exceptions import JSONDecodeError
import json 

load_dotenv()

# Load env variables
ADMIN_USER = os.getenv('ADMIN_USERNAME')
ADMIN_PASS = os.getenv('ADMIN_PASSWORD')
USER_B = os.getenv('USER_B_USERNAME')
USER_B_PASS = os.getenv('USER_B_PASSWORD')
USER_B_EMAIL = os.getenv('USER_B_EMAIL')
USER_B_MSG = os.getenv('USER_B_MESSAGE')
USER_A = os.getenv('USER_A_USERNAME')
USER_A_PASS = os.getenv('USER_A_PASSWORD')
ADMIN_FILE_CONTENTS = os.getenv('ADMIN_LOCAL_FILE')
ADMIN_FILE_NAME = os.getenv('ADMIN_FILE_NAME')
USER_B_FILE_CONTENTS=os.getenv('USER_B_LOCAL_FILE')
USER_B_FILE_NAME=os.getenv('USER_B_FILE_NAME')

BASE_URL = 'http://localhost:8080'
OCS_HEADERS = {
    "OCS-APIRequest": "true",
    "Accept": "application/json",
    "Content-Type": "application/json"
}
admin_auth = (ADMIN_USER, ADMIN_PASS)
user_b_auth = (USER_B, USER_B_PASS)
user_a_auth = (USER_A, USER_A_PASS)

def run_tests(tests):
    score = 0
    test_results = {}
    for test in tests:
        try:
            test_results[test.__name__] = test()
            score += test_results[test.__name__]
        except JSONDecodeError as e:
            print("Error in running ", test, " due to an incorrect request response.")
    return score, test_results

def obtain_scores():
    score_file = 'scores.json'
    if os.path.exists(score_file):
        with open(score_file, 'r') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = {}
    else:
        data = {}
    return data

def write_scores(data):
    score_file = 'scores.json'
    with open(score_file, 'w') as f:
        json.dump(data, f)