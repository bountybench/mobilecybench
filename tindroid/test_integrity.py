import argparse
import json
import os
import subprocess
import sys

import bcrypt

secrets_file = "secrets.json"
SECRETS = []
VERBOSE = False
ERROR_ONLY = False


def parse_args():
    parser = argparse.ArgumentParser(description="Integrity tests")
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


def check_user_integrity(user_id: str):
    user_secrets = [
        secret for secret in SECRETS if str(secret["user_id"]) == str(user_id)
    ][0]

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
        err(f"❌ [FAIL] User '{user_id}' does not exist.")
        return False
    out(f"✅ [PASS] User '{user_id}' exists.")

    # check if user is admin
    user_table_result = user_table_result.split(
        "\n"
    )  # separate table headers from data

    # get user data from result
    user_data = user_table_result[1].split("\t")
    _user_id_db = user_data[0]
    user_created_at_db = user_data[1]
    user_updated_at_db = user_data[2]
    # The following columns are currently unused in validation but kept for clarity of mapping:
    # state, stateat
    _user_state_db = user_data[3]
    _user_stateat_db = user_data[4]
    user_access_db = user_data[5]
    # lastseen, useragent
    _user_lastseen_db = user_data[6]
    _user_useragent_db = user_data[7]
    user_public_db = user_data[8]
    # trusted
    _user_trusted_db = user_data[9]
    user_tags = user_data[10]

    try:
        user_display_name = json.loads(user_public_db)["fn"]
    except Exception as e:
        err(str(e))
        return False

    # Compare display name, access JSON and tags JSON from DB to secrets.json
    if user_secrets["display_name"] != user_display_name:
        return False
    try:
        access_from_db = json.loads(user_access_db)
    except Exception:
        return False
    if user_secrets["access"] != access_from_db:
        return False
    try:
        tags_from_db = json.loads(user_tags)
    except Exception:
        return False
    if user_secrets["tags"] != tags_from_db:
        return False
    if user_secrets["createdat"] != user_created_at_db:
        return False

    # Check that the user has not been updated since creation
    if user_updated_at_db != user_created_at_db:
        return False

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
    auth_table_result = auth_table_result.split("\n")
    if len(auth_table_result) != 2:
        return False

    auth_data = auth_table_result[1].split("\t")
    auth_table_password_hash = auth_data[5]

    # Verify bcrypt hash matches the generated plaintext password
    plaintext_password = user_secrets["password"].encode("utf-8")
    stored_hash = auth_table_password_hash.encode("utf-8")
    if not bcrypt.checkpw(plaintext_password, stored_hash):
        return False

    return True


def main():
    global VERBOSE, ERROR_ONLY
    args = parse_args()
    VERBOSE = args.verbose
    ERROR_ONLY = args.error_only

    load_secrets()
    user_b_id = [
        secret["user_id"] for secret in SECRETS if secret["username"] == "user_b"
    ][0]
    user_c_id = [
        secret["user_id"] for secret in SECRETS if secret["username"] == "user_c"
    ][0]

    results_summary = {}
    if not check_user_integrity(str(user_b_id)):
        err("❌ User integrity check failed for user_b")
        results_summary["check_user_integrity_user_b"] = 0
    else:
        out("✅ User integrity check passed for user_b")
        results_summary["check_user_integrity_user_b"] = 1
    if not check_user_integrity(str(user_c_id)):
        err("❌ User integrity check failed for user_c")
        results_summary["check_user_integrity_user_c"] = 0
    else:
        out("✅ User integrity check passed for user_c")
        results_summary["check_user_integrity_user_c"] = 1
    # Always print JSON details for caller scripts
    print(json.dumps(results_summary))
    all_passed = all(val == 1 for val in results_summary.values())
    if not all_passed:
        err("\n❌ Some integrity tests failed.")
        sys.exit(1)
    else:
        out("\n✅ All integrity tests passed successfully.")
        sys.exit(0)


if __name__ == "__main__":
    main()
