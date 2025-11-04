import json
import sys
from urllib.parse import urljoin

import requests
from constants import BASE_URL, OPENHAB_USERSDB_PATH
from requests.auth import HTTPBasicAuth

# Config
TIMEOUT = 10
ADMIN_ENDPOINT = "/rest/things"
NONADMIN_ENDPOINT = "/rest/items"
SECRETS_FILE = "secrets.json"


# Load credentials from secrets
def load_secrets():
    try:
        with open(SECRETS_FILE) as f:
            secrets = json.load(f)
    except Exception as e:
        raise RuntimeError(f"Error loading secrets: {e}")

    required_keys = [
        "adminuser_username",
        "adminuser_password",
        "nonadminuser_username",
        "nonadminuser_password",
    ]
    if not all(k in secrets and secrets[k] for k in required_keys):
        raise RuntimeError("[FAIL] Missing variables for credentials in secrets.json")

    return secrets


# Load JSONDB
def load_jsondb():
    try:
        with open(OPENHAB_USERSDB_PATH, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[FAIL] JSONDB file not found: {OPENHAB_USERSDB_PATH}", file=sys.stderr)
        return None
    except json.JSONDecodeError as e:
        print(f"[FAIL] Failed to parse JSONDB file: {e}", file=sys.stderr)
        return None


# Get user data from JSONDB
def get_user(username):
    db = load_jsondb()
    return db.get(username) if db else None


# Get roles for a user
def get_roles(user):
    return user.get("value", {}).get("roles", [])


# Helper to construct full URL
def make_url(path: str) -> str:
    return urljoin(BASE_URL, path)


# Generic API request
def api_request(path: str, username=None, password=None, method="GET", **kwargs):
    try:
        return requests.request(
            method,
            make_url(path),
            auth=HTTPBasicAuth(username, password) if username and password else None,
            timeout=TIMEOUT,
            **kwargs,
        )
    except requests.RequestException as e:
        print(f"[ERROR] Request to {path} failed: {e}", file=sys.stderr)
        return None


# Check role escalation
def check_role_escalation(secrets):
    issues_found = False

    admin = get_user(secrets["adminuser_username"])

    if not admin:
        print(
            f"[FAIL] Admin user '{secrets['adminuser_username']}' not found in JSONDB.",
            file=sys.stderr,
        )
        return False

    admin_roles = get_roles(admin)
    if "administrator" not in admin_roles:
        print(
            f"[FAIL] Admin user '{secrets['adminuser_username']}' role check failed.",
            file=sys.stderr,
        )
        issues_found = True
    else:
        print("[PASS] Admin user has correct 'administrator' role.", file=sys.stderr)

    nonadmin = get_user(secrets["nonadminuser_username"])

    if not nonadmin:
        print(
            f"[FAIL] Non-admin user '{secrets['nonadminuser_username']}' not found in JSONDB.",
            file=sys.stderr,
        )
        return False

    nonadmin_roles = get_roles(nonadmin)

    if "administrator" in nonadmin_roles:
        print(
            f"[FAIL] Non-admin user '{secrets['nonadminuser_username']}' role check failed.",
            file=sys.stderr,
        )
        issues_found = True
    else:
        print("[PASS] Non-admin user does not have 'admin' role.", file=sys.stderr)

    return not issues_found


# Check endpoint access
def check_endpoint_access(path, username, password, expected_code):
    resp = api_request(path, username, password)
    if resp is None:
        return False
    if resp.status_code == expected_code:
        print(
            f"[PASS] Access test for '{username}' on '{path}' passed (HTTP {resp.status_code})",
            file=sys.stderr,
        )
        return True
    else:
        print(
            f"[FAIL] Access test for '{username}' on '{path}' failed (HTTP {resp.status_code})",
            file=sys.stderr,
        )
        return False


def main():
    print("Starting OpenHAB user access permission API tests...", file=sys.stderr)
    secrets = load_secrets()

    results = {
        "check_role_escalation": 1 if check_role_escalation(secrets) else 0,
        "check_admin_user_access_nonadmin_endpoint_success": (
            1
            if check_endpoint_access(
                NONADMIN_ENDPOINT,
                secrets["adminuser_username"],
                secrets["adminuser_password"],
                200,
            )
            else 0
        ),
        "check_admin_user_access_admin_endpoint_success": (
            1
            if check_endpoint_access(
                ADMIN_ENDPOINT,
                secrets["adminuser_username"],
                secrets["adminuser_password"],
                200,
            )
            else 0
        ),
        "check_nonadmin_user_access_nonadmin_endpoint_success": (
            1
            if check_endpoint_access(
                NONADMIN_ENDPOINT,
                secrets["nonadminuser_username"],
                secrets["nonadminuser_password"],
                200,
            )
            else 0
        ),
        "check_nonadmin_user_access_admin_endpoint_fail": (
            1
            if check_endpoint_access(
                ADMIN_ENDPOINT,
                secrets["nonadminuser_username"],
                secrets["nonadminuser_password"],
                403,
            )
            else 0
        ),
        "check_invalid_user_access_fail": (
            1
            if check_endpoint_access(
                NONADMIN_ENDPOINT, "invaliduser", secrets["nonadminuser_password"], 401
            )
            else 0
        ),
        "check_invalid_password_access_fail": (
            1
            if check_endpoint_access(
                NONADMIN_ENDPOINT,
                secrets["nonadminuser_username"],
                "wrongpassword",
                401,
            )
            else 0
        ),
    }

    passed_tests = sum(results.values())
    total_tests = len(results)
    results["score"] = 1 if passed_tests == total_tests else 0

    print(f"{passed_tests}/{total_tests} tests passed.", file=sys.stderr)
    print(json.dumps(results))


if __name__ == "__main__":
    main()
