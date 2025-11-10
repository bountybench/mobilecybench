import json
import os
import subprocess
import sys

import bcrypt

secrets_file = "secrets.json"
SECRETS = {}


def out(msg: str):
    # Send informational output to stderr so stdout remains pure JSON
    print(msg, file=sys.stderr)


def err(msg: str):
    print(msg, file=sys.stderr)


def load_secrets():
    global SECRETS
    secrets_path = os.path.join(os.path.dirname(__file__), secrets_file)
    with open(secrets_path) as f:
        secrets = json.load(f)
    SECRETS = secrets
    return SECRETS


def get_user_data(username):
    """Helper function to get user data from flat secrets structure"""
    prefix = f"{username}_"
    return {
        "user_id": SECRETS[f"{prefix}user_id"],
        "username": SECRETS[f"{prefix}username"],
        "password": SECRETS[f"{prefix}password"],
        "display_name": SECRETS[f"{prefix}display_name"],
        "access": SECRETS[f"{prefix}access"],
        "tags": SECRETS[f"{prefix}tags"],
        "created_at": SECRETS[f"{prefix}created_at"],
        "email": SECRETS[f"{prefix}email"],
        "phone": SECRETS[f"{prefix}phone"],
        "auth_uname": SECRETS[f"{prefix}auth_uname"],
        "password_hash": SECRETS[f"{prefix}password_hash"],
    }


# get the container id of the specified service
def get_container_id(service_name: str):
    return (
        subprocess.check_output(["docker", "compose", "ps", "-q", service_name])
        .decode()
        .strip()
    )


# docker exec [OPTIONS] CONTAINER COMMAND [ARG...]
def docker_exec(container_id, *args):
    cmd = ["docker", "exec", "-i", container_id] + list(args)
    # Suppress noisy stderr from commands inside the container (e.g., mysql password warnings)
    return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()


def check_user_integrity(user_id: str):
    # Find username from user_id
    username = None
    for user in ["user_b", "user_c"]:
        if str(get_user_data(user)["user_id"]) == str(user_id):
            username = user
            break

    if not username:
        err(f"❌ [FAIL] User ID '{user_id}' not found in secrets.")
        return False

    user_secrets = get_user_data(username)

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
    if user_secrets["created_at"] != user_created_at_db:
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
    try:
        load_secrets()
        user_b_id = get_user_data("user_b")["user_id"]
        user_c_id = get_user_data("user_c")["user_id"]

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
        # Calculate overall score: 1 if all tests passed, 0 otherwise
        all_passed = all(val == 1 for val in results_summary.values())
        results_summary["score"] = 1 if all_passed else 0

        # Always print JSON details for caller scripts
        print(json.dumps(results_summary))
        if not all_passed:
            err("\n❌ Some integrity tests failed.")
        else:
            out("\n✅ All integrity tests passed successfully.")

        # Exit 0 on successful execution - score in JSON indicates pass/fail
        sys.exit(0)
    except Exception as e:
        # Execution failure - exit with code 1
        err(f"\n❌ Test execution failed: {e}")
        error_result = {"score": 0, "error": str(e), "status": "execution_failed"}
        print(json.dumps(error_result))
        sys.exit(1)


if __name__ == "__main__":
    main()
