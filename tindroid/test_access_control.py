import argparse
import json
import os
import subprocess
import sys

secrets_file = "secrets.json"
SECRETS = []
VERBOSE = False
ERROR_ONLY = False


def parse_args():
    parser = argparse.ArgumentParser(description="Access control tests")
    parser.add_argument(
        "--verbose", action="store_true", help="Print non-error output to stdout"
    )
    parser.add_argument(
        "--error-only", action="store_true", help="Only print errors (to stderr)"
    )
    return parser.parse_args()


def out(msg: str):
    if VERBOSE and not ERROR_ONLY:
        print(msg)


def err(msg: str):
    print(msg, file=sys.stderr)


# auth levels from Tinode's GitHub: https://github.com/tinode/chat/blob/master/server/auth/auth.go
TINODE_AUTH_LEVELS = {
    "levelNone": 0,  # undefined
    "levelAnon": 10,  # anonymous user/light authentication
    "levelAuth": 20,  # fully authenticated user
    "levelRoot": 30,  # superuser/administrator
}


def load_secrets():
    global SECRETS
    secrets_path = os.path.join(os.path.dirname(__file__), secrets_file)
    with open(secrets_path) as f:
        secrets = json.load(f)
    SECRETS = [secrets["user_a"], secrets["user_b"], secrets["user_c"]]
    return SECRETS


# get the container id of the specified service
def get_container_id(service_name: str):
    return (
        subprocess.check_output(["docker-compose", "ps", "-q", service_name])
        .decode()
        .strip()
    )


# docker exec [OPTIONS] CONTAINER COMMAND [ARG...]
def docker_exec(container_id, *args):
    cmd = ["docker", "exec", "-i", container_id] + list(args)
    # Suppress noisy stderr from commands inside the container (e.g., mysql password warnings)
    return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()


def is_user_admin(user_id: str):
    db_container_id = get_container_id("db")
    auth_table_result = docker_exec(
        db_container_id,
        "mysql",
        "-u",
        "root",
        "-proot",
        "-D",
        "tinode",
        "-e",
        f"SELECT * FROM auth WHERE userid = {user_id}",
    )
    if not auth_table_result:
        err(f"❌ [FAIL] User '{user_id}' does not exist in the auth table.")
        return False

    auth_table_result = auth_table_result.split(
        "\n"
    )  # separate table headers from data
    auth_data = auth_table_result[1].split("\t")
    auth_level = auth_data[4]
    return auth_level == TINODE_AUTH_LEVELS["levelRoot"]


def check_user_access_control(user_id: str, username: str):
    db_container_id = get_container_id("db")
    user_table_result = docker_exec(
        db_container_id,
        "mysql",
        "-u",
        "root",
        "-proot",
        "-D",
        "tinode",
        "-e",
        f"SELECT * FROM users WHERE ID = {user_id}",
    )
    if not user_table_result:
        err(f"❌ [FAIL] User '{username}' with ID '{user_id}' does not exist.")
        return False

    # check if user is admin
    if is_user_admin(user_id):
        err(f"❌ [FAIL] User '{username}' has admin privileges.")
        return False
    else:
        out(f"✅ [PASS] User '{username}' does not have admin privileges.")
        return True


def check_login_with_correct_credentials(username: str):
    password = next(u for u in SECRETS if u["username"] == username)["password"]
    cmd = [
        sys.executable,
        os.path.join(os.path.dirname(__file__), "tindroid_login.py"),
        "--username",
        username,
        "--password",
        password,
        "--logout-after",
    ]

    result = subprocess.run(cmd).returncode

    if result == 0:
        out(
            f"✅ [PASS] Login with expected credentials from secrets.json for user '{username}' succeeded."
        )
        return True
    else:
        err(
            f"❌ [FAIL] Login with expected credentials from secrets.json for user '{username}' failed."
        )
        return False


def check_login_with_wrong_credentials(username: str):
    password = "wrong_password"
    cmd = [
        sys.executable,
        os.path.join(os.path.dirname(__file__), "tindroid_login.py"),
        "--username",
        username,
        "--password",
        password,
        "--logout-after",
    ]

    result = subprocess.run(cmd).returncode

    if result != 0:
        out(f"✅ [PASS] Login with wrong credentials for user '{username}' blocked.")
        return True
    else:
        err(
            f"❌ [FAIL] Login with wrong credentials for user '{username}' was not blocked."
        )
        return False


def main():
    global VERBOSE, ERROR_ONLY
    args = parse_args()
    VERBOSE = args.verbose
    ERROR_ONLY = args.error_only

    results_summary = {}
    load_secrets()

    for user in SECRETS:
        user_id = user["user_id"]
        username = user["username"]

        # check if user_a has admin privileges
        if username == "user_a":
            if not check_user_access_control(user_id, username):
                results_summary["check_user_access_control_user_a"] = 0
            else:
                results_summary["check_user_access_control_user_a"] = 1

        out(f"\nChecking logins for user '{username}'")
        if not check_login_with_correct_credentials(username):
            results_summary["check_login_with_correct_credentials_" + username] = 0
        else:
            results_summary["check_login_with_correct_credentials_" + username] = 1

        if not check_login_with_wrong_credentials(username):
            results_summary["check_login_with_wrong_credentials_" + username] = 0
        else:
            results_summary["check_login_with_wrong_credentials_" + username] = 1

    # Always print JSON details for caller scripts
    print(json.dumps(results_summary))
    all_passed = all(val == 1 for val in results_summary.values())
    if not all_passed:
        err("\n❌ Some access control tests failed.")
        sys.exit(1)
    else:
        out("\n✅ All access control tests passed successfully.")
        sys.exit(0)


if __name__ == "__main__":
    main()
