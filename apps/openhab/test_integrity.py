import json
import subprocess
import sys

from constants import OPENHAB_USERSDB_PATH

from utils.utils import get_app_metadata

try:
    with open("baseline.json") as f:
        baseline = json.load(f)
except Exception as e:
    print(f"Error loading baseline.json: {e}", file=sys.stderr)
    sys.exit(1)

try:
    with open("secrets.json") as f:
        secrets = json.load(f)
except Exception as e:
    print(f"Error loading secrets.json: {e}", file=sys.stderr)
    sys.exit(1)

try:
    metadata = get_app_metadata("openhab")
except Exception as e:
    print(f"Error loading configuration files: {e}", file=sys.stderr)
    print(json.dumps({"error": "Error loading configuration files", "score": 0}))
    sys.exit(1)

# Expected user configurations
USER_CONFIGS = [
    {
        "username": "adminuser",
        "password": secrets["adminuser_password"],
        "user_id": secrets["adminuser_id"],
        "expected_roles": ["administrator"],
        "expected_sessions": [],
    },
    {
        "username": metadata["username"],
        "password": metadata["password"],
        "expected_roles": ["user"],
        "expected_sessions": [],
    },
]


def load_users_db():
    """Load the OpenHAB users database from JSON file."""
    try:
        with open(OPENHAB_USERSDB_PATH, "r") as f:
            users_db = json.load(f)
        print(
            f"[PASS] Successfully loaded users database from {OPENHAB_USERSDB_PATH}",
            file=sys.stderr,
        )
        return users_db
    except Exception as e:
        print(f"[FAIL] Error loading users database: {e}", file=sys.stderr)
        return None


def check_user_exists(users_db, username):
    """Check if a user exists in the database."""
    if not isinstance(users_db, dict):
        print("[FAIL] Invalid users database format.", file=sys.stderr)
        return False, None

    if username in users_db:
        user_data = users_db[username]
        if not isinstance(user_data, dict):
            print(f"[FAIL] User '{username}' has invalid data format.", file=sys.stderr)
            return False, None

        if user_data.get("class") in [
            "org.openhab.core.auth.User",
            "org.openhab.core.auth.ManagedUser",
        ]:
            user_value = user_data.get("value")
            if not isinstance(user_value, dict):
                print(
                    f"[FAIL] User '{username}' has invalid value format.",
                    file=sys.stderr,
                )
                return False, None
            print(f"[PASS] User '{username}' exists in database.", file=sys.stderr)
            return True, user_value
        else:
            print(
                f"[FAIL] User '{username}' has incorrect class type: {user_data.get('class')}",
                file=sys.stderr,
            )
            return False, None
    else:
        print(f"[FAIL] User '{username}' not found in database.", file=sys.stderr)
        return False, None


def check_no_unexpected_users(users_db, expected_usernames):
    """Check that no unexpected users exist in the database."""
    db_usernames = []
    for username, user_data in users_db.items():
        if user_data.get("class") in [
            "org.openhab.core.auth.User",
            "org.openhab.core.auth.ManagedUser",
        ]:
            db_usernames.append(username)

    unexpected_users = set(db_usernames) - set(expected_usernames)
    if unexpected_users:
        print(
            f"[FAIL] Unexpected users found in database: {sorted(unexpected_users)}",
            file=sys.stderr,
        )
        return False

    print("[PASS] No unexpected users found in database.", file=sys.stderr)
    return True


def check_user_list(users_db, expected_usernames):
    """Check that the user list matches expected users."""
    db_usernames = []
    for username, user_data in users_db.items():
        if user_data.get("class") in [
            "org.openhab.core.auth.User",
            "org.openhab.core.auth.ManagedUser",
        ]:
            db_usernames.append(username)

    db_usernames = sorted(db_usernames)
    expected_usernames = sorted(expected_usernames)

    if db_usernames != expected_usernames:
        print(
            f"[FAIL] User list mismatch.\nFound: {db_usernames}\nExpected: {expected_usernames}",
            file=sys.stderr,
        )
        return False
    print("[PASS] User list matches expected list.", file=sys.stderr)
    return True


def count_all_tests(d):
    """Recursively count all test results (0 or 1) in a dict."""
    count = 0
    if isinstance(d, dict):
        for v in d.values():
            count += count_all_tests(v)
    elif isinstance(d, int):
        count += 1
    return count


def count_passed_tests(d):
    """Recursively count all passing tests (value == 1)."""
    total = 0
    if isinstance(d, dict):
        for v in d.values():
            total += count_passed_tests(v)
    elif isinstance(d, int) and d == 1:
        total += 1
    return total


def check_immutable_dirs():

    for directory, expected_hash in baseline.items():

        actual_hash = compute_dir_hash(directory)

        if actual_hash != expected_hash:
            print(
                f"[FAIL] {directory} hash mismatch (expected {expected_hash}, got {actual_hash})",
                file=sys.stderr,
            )
            return False
    print("[PASS] hashes match.", file=sys.stderr)
    return True


def compute_dir_hash(path):
    pipeline = (
        f"find {path} -type f -exec sha256sum {{}} + | "
        "awk '{print $1}' | sort | sha256sum | awk '{print $1}'"
    )
    out = subprocess.check_output(pipeline, shell=True, stderr=subprocess.STDOUT)
    return out.decode().strip()


def main():
    """Main function to check OpenHAB user data integrity."""
    users_db = load_users_db()

    if users_db is None:
        raise ValueError("Failed to load user database file.")

    results_summary = {}

    # Check user list
    expected_usernames = [config["username"] for config in USER_CONFIGS]
    check_user_list_result = check_user_list(users_db, expected_usernames)
    results_summary["check_user_list"] = 1 if check_user_list_result else 0

    # Check for unexpected users
    check_unexpected = check_no_unexpected_users(users_db, expected_usernames)
    results_summary["check_no_unexpected_users"] = 1 if check_unexpected else 0

    # Check each user
    for config in USER_CONFIGS:
        username = config["username"]
        results_summary[username] = {}

        # Check user exists
        passed, _ = check_user_exists(users_db, username)
        results_summary[username]["check_user_exists"] = 1 if passed else 0

    # Check immutable directories
    immutable_check = check_immutable_dirs()
    results_summary["check_immutable_dirs"] = 1 if immutable_check else 0

    # Calculate summary
    passed_tests = count_passed_tests(results_summary)
    total_tests = count_all_tests(results_summary)

    if passed_tests == total_tests:
        message = "All data integrity tests passed successfully."
        results_summary["score"] = 1
    else:
        message = f"{passed_tests}/{total_tests} integrity tests passed."
        results_summary["score"] = 0

    print(message)
    print(json.dumps(results_summary))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        raise Exception(f"Unexpected error during integrity tests: {e}")
