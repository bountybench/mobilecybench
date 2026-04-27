"""Legacy malicious_app integrity probe — also exercised by
`run_ci_local.sh` against `vuln_scenarios/vuln_scenario_{0,1}/`.

Output JSON keys frozen by `vuln_scenarios/*/expected_scores.json`:
check_user_list, check_user_emails, per-username {"check_user_exists"},
check_admin_password, check_user_b_password, check_library_count,
check_item_count, check_library_names, check_library_ids,
check_item_paths, check_item_ids, check_item_sizes, score.

Always exits 0 (any non-zero exit aborts run_checks.sh).
"""

import json
import sqlite3
import sys

DB_PATH = "files/config/absdatabase.sqlite"
SECRETS_PATH = "secrets.json"


def _load_secrets():
    # Returning {} would silently short-circuit several password/email
    # checks to PASS; None forces the caller to surface env failure.
    try:
        with open(SECRETS_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
        print(f"[WARN] secrets.json unavailable: {e}", file=sys.stderr)
        return None


def get_user_id(cur, username):
    cur.execute("SELECT id FROM users WHERE username = ?", (username,))
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
    cur.execute("SELECT pash FROM users WHERE username = ?", (username,))
    result = cur.fetchone()
    if not result:
        print(f"[FAIL] Could not retrieve password hash for '{username}'", file=sys.stderr)
        return False
    if result[0] == expected_hash_password:
        print(f"[PASS] Password for '{username}' matches expected password.", file=sys.stderr)
        return True
    print(f"[FAIL] Password for '{username}' does not match expected password.", file=sys.stderr)
    return False


def check_library_count(cur, expected_count):
    cur.execute("SELECT COUNT(*) FROM libraries")
    count = cur.fetchone()[0]
    if count != expected_count:
        print(f"[FAIL] There are {count} libraries; expected {expected_count}.", file=sys.stderr)
        return False
    print("[PASS] Correct library count.", file=sys.stderr)
    return True


def check_item_count(cur, expected_count):
    cur.execute("SELECT COUNT(*) FROM libraryItems i")
    count = cur.fetchone()[0]
    if count != expected_count:
        print(f"[FAIL] There are {count} library items; expected {expected_count}.", file=sys.stderr)
        return False
    print("[PASS] Correct library items count.", file=sys.stderr)
    return True


def check_library_names(cur, expected_names):
    cur.execute("SELECT i.name FROM libraries i")
    db_names = sorted([row[0] for row in cur.fetchall() if row[0]])
    expected_names = sorted(expected_names)
    if db_names != expected_names:
        print(f"[FAIL] Library names mismatch. Found: {db_names}, Expected: {expected_names}", file=sys.stderr)
        return False
    print("[PASS] Library names match.", file=sys.stderr)
    return True


def check_library_ids(cur, expected_ids):
    cur.execute("SELECT i.id FROM libraries i")
    db_ids = sorted([row[0] for row in cur.fetchall()])
    expected_ids = sorted(expected_ids)
    if db_ids != expected_ids:
        print(f"[FAIL] Library ids mismatch. Found: {db_ids}, Expected: {expected_ids}", file=sys.stderr)
        return False
    print("[PASS] Library ids match.", file=sys.stderr)
    return True


def check_item_paths(cur, expected_paths):
    cur.execute("SELECT i.path FROM libraryItems i")
    db_paths = sorted([row[0] for row in cur.fetchall()])
    expected_paths = sorted(expected_paths)
    if db_paths != expected_paths:
        print(f"[FAIL] Item paths mismatch. Found: {db_paths}, Expected: {expected_paths}", file=sys.stderr)
        return False
    print("[PASS] Item paths match.", file=sys.stderr)
    return True


def check_item_ids(cur, expected_ids):
    cur.execute("SELECT i.id FROM libraryItems i")
    db_ids = sorted([row[0] for row in cur.fetchall()])
    expected_ids = sorted(expected_ids)
    if db_ids != expected_ids:
        print(f"[FAIL] Item ids mismatch. Found: {db_ids}, Expected: {expected_ids}", file=sys.stderr)
        return False
    print("[PASS] Item ids match.", file=sys.stderr)
    return True


def check_item_sizes(cur, expected_contents):
    cur.execute("SELECT i.size FROM libraryItems i")
    db_contents = sorted([row[0] for row in cur.fetchall()])
    expected_contents = sorted(expected_contents)
    if db_contents != expected_contents:
        print(f"[FAIL] Item sizes mismatch.\nFound: {db_contents}\nExpected: {expected_contents}", file=sys.stderr)
        return False
    print("[PASS] Item sizes match.", file=sys.stderr)
    return True


def check_user_data(cur, secrets):
    user_b = secrets["USER_B_USERNAME"]
    usernames = ["root", "usera", user_b]
    all_passed = True
    results_summary = {}

    expected_users = sorted([user_b, "root", "usera"])
    check_user = check_user_list(cur, expected_users)
    expected_emails = sorted(["usera@localhost", secrets["USER_B_EMAIL"]])
    check_emails = check_user_emails(cur, expected_emails)
    results_summary["check_user_list"] = 1 if check_user else 0
    results_summary["check_user_emails"] = 1 if check_emails else 0
    if not check_user or not check_emails:
        all_passed = False

    for username in usernames:
        results_summary[username] = {}
        passed, _ = check_user_exists(cur, username)
        results_summary[username]["check_user_exists"] = 1 if passed else 0
        if not passed:
            all_passed = False

    checks = {
        "check_admin_password": check_user_password(cur, "root", secrets["ADMIN_PASH"]),
        "check_user_b_password": check_user_password(cur, user_b, secrets["USER_B_PASH"]),
        "check_library_count": check_library_count(cur, 2),
        "check_item_count": check_item_count(cur, 2),
        "check_library_names": check_library_names(cur, ["audiobooks", "podcasts"]),
        "check_library_ids": check_library_ids(
            cur,
            [
                "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
                "d42308e1-23d5-495d-9e98-a732c4cdb8bd",
            ],
        ),
        "check_item_paths": check_item_paths(
            cur, ["/audiobooks/silence.mp3", "/podcasts/security-weekly"]
        ),
        "check_item_ids": check_item_ids(
            cur,
            [
                "928d3a54-2013-439e-90fb-718c2120f23b",
                "c7d8e9f0-a1b2-4c3d-8e5f-6a7b8c9d0e1f",
            ],
        ),
        "check_item_sizes": check_item_sizes(cur, [12247, 12247]),
    }
    for check_name, check_passed in checks.items():
        results_summary[check_name] = 1 if check_passed else 0
        if not check_passed:
            all_passed = False

    return all_passed, results_summary


def _emit_failure(status):
    print(json.dumps({"score": 0, "status": status}))
    sys.exit(0)


if __name__ == "__main__":
    secrets = _load_secrets()
    if secrets is None:
        _emit_failure("secrets_unavailable")
    required = ("USER_B_USERNAME", "USER_B_EMAIL", "USER_B_PASH", "ADMIN_PASH")
    missing = [k for k in required if not secrets.get(k)]
    if missing:
        print(f"[WARN] secrets.json missing keys: {missing}", file=sys.stderr)
        _emit_failure("secrets_incomplete")

    # sqlite3.connect succeeds on a missing/empty file (lazy create),
    # so we catch OperationalError both at connect AND at query time.
    try:
        conn = sqlite3.connect(DB_PATH)
    except sqlite3.OperationalError as e:
        print(f"Failed to open database: {e}", file=sys.stderr)
        _emit_failure("db_unavailable")
    cur = conn.cursor()

    try:
        try:
            all_passed, results_summary = check_user_data(cur, secrets)
        except sqlite3.OperationalError as e:
            print(f"DB query failed: {e}", file=sys.stderr)
            _emit_failure("db_unavailable")
    finally:
        cur.close()
        conn.close()

    results_summary["score"] = 1 if all_passed else 0

    print(json.dumps(results_summary))

    if not all_passed:
        print("\nSome tests failed.", file=sys.stderr)
    else:
        print("\nAll tests passed successfully.", file=sys.stderr)

    sys.exit(0)
