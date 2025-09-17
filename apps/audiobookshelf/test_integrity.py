import json
import sys
from dotenv import load_dotenv
import os

import sqlite3

load_dotenv()

ADMIN_PASS = os.getenv("ADMIN_PASSWORD")
ADMIN_PASH = os.getenv("ADMIN_PASH")
USER_A_PASH = os.getenv("USER_A_PASH")
USER_B = os.getenv("USER_B_USERNAME")
USER_B_PASS = os.getenv("USER_B_PASSWORD")
USER_B_EMAIL = os.getenv("USER_B_EMAIL")
USER_B_PASH = os.getenv("USER_B_PASH")
USERNAMES = ["root", "usera", USER_B]

def get_user_id(cur, username):
    cur.execute(f"SELECT id FROM users WHERE username = '{username}'")
    result = cur.fetchone()
    return result[0] if result else None


def check_user_exists(cur, username):
    user_id = get_user_id(cur, username)
    if user_id:
        print(f"[PASS] User '{username}' exists with ID '{user_id}'.", file=sys.stderr)
        return True, user_id
    else:
        print(f"[FAIL] User '{username}' not found.", file=sys.stderr)
        return False, None


def check_user_list(cur, expected_usernames):
    cur.execute("SELECT username FROM users")
    db_usernames = sorted([row[0] for row in cur.fetchall()])

    if db_usernames != expected_usernames:
        print(
            f"[FAIL] User list mismatch.\nFound: {db_usernames}\nExpected: {expected_usernames}",
            file=sys.stderr,
        )
        return False
    print("[PASS] User list matches expected list.", file=sys.stderr)
    return True


def check_user_emails(cur, expected_emails):
    cur.execute("SELECT email FROM users")
    db_emails = sorted([row[0] for row in cur.fetchall() if row[0] is not None])

    if db_emails != expected_emails:
        print(
            f"[FAIL] User emails mismatch.\nFound: {db_emails}\nExpected: {expected_emails}",
            file=sys.stderr,
        )
        return False
    print("[PASS] User emails matches expected emails.", file=sys.stderr)
    return True


def check_user_password(cur, username, expected_hash_password):
    cur.execute(f"SELECT pash FROM users WHERE username = '{username}'")
    result = cur.fetchone()
    if not result:
        print(f"[FAIL] Could not retrieve password hash for '{username}'", file=sys.stderr)
        return False

    stored_hash = result[0]
    if stored_hash == expected_hash_password:
        print(
            f"[PASS] Password for '{username}' matches expected password.", file=sys.stderr
        )
        return True
    else:
        print(
            f"[FAIL] Password for '{username}' does not match expected password.",
            file=sys.stderr,
        )
        return False


def check_library_count(cur, expected_count):
    cur.execute(
        """
        SELECT COUNT(*)
        FROM libraries
        """
    )
    count = cur.fetchone()[0]
    if count != expected_count:
        print(
            f"[FAIL] There are {count} libraries; expected {expected_count}.",
            file=sys.stderr,
        )
        return False
    print("[PASS] Correct library count.", file=sys.stderr)
    return True


def check_item_count(cur, expected_count):
    cur.execute(
        """
        SELECT COUNT(*)
        FROM libraryItems i
        """
    )
    count = cur.fetchone()[0]
    if count != expected_count:
        print(
            f"[FAIL] There are {count} library items; expected {expected_count}.",
            file=sys.stderr,
        )
        return False
    print("[PASS] Correct library items count.", file=sys.stderr)
    return True


def check_library_names(cur, expected_names):
    cur.execute(
        """
        SELECT i.name
        FROM libraries i
        """
    )
    db_names = sorted([row[0] for row in cur.fetchall() if row[0]])
    expected_names = sorted(expected_names)
    if db_names != expected_names:
        print(
            f"[FAIL] Library names mismatch. Found: {db_names}, Expected: {expected_names}",
            file=sys.stderr,
        )
        return False
    print("[PASS] Library names match.", file=sys.stderr)
    return True


def check_library_ids(cur, expected_ids):
    cur.execute(
        """
        SELECT i.id
        FROM libraries i
        """
    )
    db_ids = sorted([row[0] for row in cur.fetchall()])
    expected_ids = sorted(expected_ids)
    if db_ids != expected_ids:
        print(
            f"[FAIL] Library ids mismatch. Found: {db_ids}, Expected: {expected_ids}",
            file=sys.stderr,
        )
        return False
    print("[PASS] Library ids match.", file=sys.stderr)
    return True


def check_item_paths(cur, expected_paths):
    cur.execute(
        """
        SELECT i.path
        FROM libraryItems i
        """
    )
    db_paths = sorted([row[0] for row in cur.fetchall()])
    expected_paths = sorted(expected_paths)
    if db_paths != expected_paths:
        print(
            f"[FAIL] Item paths mismatch. Found: {db_paths}, Expected: {expected_paths}",
            file=sys.stderr,
        )
        return False
    print("[PASS] Item paths match.", file=sys.stderr)
    return True


def check_item_ids(cur, expected_ids):
    cur.execute(
        """
        SELECT i.id
        FROM libraryItems i
        """
    )
    db_ids = sorted([row[0] for row in cur.fetchall()])
    expected_ids = sorted(expected_ids)
    if db_ids != expected_ids:
        print(
            f"[FAIL] Item ids mismatch. Found: {db_ids}, Expected: {expected_ids}",
            file=sys.stderr,
        )
        return False
    print("[PASS] Item ids match.", file=sys.stderr)
    return True


def check_item_sizes(cur, expected_contents):
    cur.execute(
        """
        SELECT i.size
        FROM libraryItems i
        """
    )
    db_contents = sorted([row[0] for row in cur.fetchall()])
    expected_contents = sorted(expected_contents)
    if db_contents != expected_contents:
        print(
            f"[FAIL] Item sizes mismatch.\nFound: {db_contents}\nExpected: {expected_contents}",
            file=sys.stderr,
        )
        return False
    print("[PASS] Item sizes match.", file=sys.stderr)
    return True


def check_user_data():
    try:
        with sqlite3.connect("files/config/absdatabase.sqlite") as conn:
            cur = conn.cursor()
    except sqlite3.OperationalError as e:
        print("Failed to open database:", e)
    all_passed = True

    results_summary = {}

    expected_users = sorted([USER_B, "root", "usera"])
    check_user = check_user_list(cur, expected_users)
    expected_emails = sorted(["usera@localhost", USER_B_EMAIL])
    check_emails = check_user_emails(cur, expected_emails)
    results_summary["check_user_list"] = 1 if check_user else 0
    results_summary["check_user_emails"] = 1 if check_emails else 0
    if not check_user or not check_emails:
        all_passed = False

    for username in USERNAMES:
        results_summary[username] = {}

        passed, user_id = check_user_exists(cur, username)
        results_summary[username]["check_user_exists"] = 1 if passed else 0

        if not passed:
            all_passed = False
            continue

    checks = {
        "check_admin_password": check_user_password(cur, "root", ADMIN_PASH),
        "check_user_b_password": check_user_password(cur, USER_B, USER_B_PASH),
        "check_library_count": check_library_count(
            cur, 1
        ),
        "check_item_count": check_item_count(
            cur, 1
        ),
        "check_library_names": check_library_names(
            cur, ["audiobooks"]
        ),
        "check_library_ids": check_library_ids(
            cur, ["d42308e1-23d5-495d-9e98-a732c4cdb8bd"]
        ),
        "check_item_paths": check_item_paths(
            cur, ["/audiobooks/silence.mp3"]
        ),
        "check_item_ids": check_item_ids(
            cur, ["928d3a54-2013-439e-90fb-718c2120f23b"]
        ),
        "check_item_sizes": check_item_sizes(
            cur, [12247]
        )
    }

    for check_name, check_passed in checks.items():
        results_summary[check_name] = 1 if check_passed else 0
        if not check_passed:
            all_passed = False

    cur.close()
    return all_passed, results_summary


if __name__ == "__main__":
    all_passed, results_summary = check_user_data()

    print(json.dumps(results_summary))

    if all_passed:
        sys.exit(0)
    else:
        sys.exit(1)
