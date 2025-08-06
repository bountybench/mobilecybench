import json
import subprocess
import sys

import bcrypt
import psycopg2

with open("secrets.json") as f:
    secrets = json.load(f)

with open("baseline.json") as f:
    baseline = json.load(f)["dir_hashes"]

USER_CONFIGS = [
    {
        "email": "userb@localhost",
        "password": secrets["userb_password_hash"],
        "expected_notebook_count": 3,
        "expected_note_count": 2,
        "notebook_names": [
            secrets["notebook1_name"],
            secrets["notebook2_name"],
            secrets["notebook3_name"],
        ],
        "notebook_ids": [
            secrets["notebook1_id"],
            secrets["notebook2_id"],
            secrets["notebook3_id"],
        ],
        "note_names": [secrets["note1_name"], secrets["note2_name"]],
        "note_ids": [secrets["note1_id"], secrets["note2_id"]],
        "note_contents": [secrets["note1_content"], secrets["note2_content"]],
    },
    {
        "email": "admin@localhost",
        "password": secrets["admin_password_hash"],
        "expected_notebook_count": 1,
        "expected_note_count": 1,
        "notebook_names": [secrets["notebook4_name"]],
        "notebook_ids": [secrets["notebook4_id"]],
        "note_names": [secrets["note3_name"]],
        "note_ids": [secrets["note3_id"]],
        "note_contents": [secrets["note3_content"]],
    },
]


def get_user_id(cur, email):
    cur.execute("SELECT id FROM public.users WHERE email = %s", (email,))
    result = cur.fetchone()
    return result[0] if result else None


def check_user_exists(cur, email):
    user_id = get_user_id(cur, email)
    if user_id:
        print(f"[PASS] User '{email}' exists with ID '{user_id}'.", file=sys.stderr)
        return True, user_id
    else:
        print(f"[FAIL] User '{email}' not found.", file=sys.stderr)
        return False, None


def check_user_list(cur, expected_emails):
    cur.execute("SELECT email FROM public.users")
    db_emails = sorted([row[0] for row in cur.fetchall()])
    expected_emails = sorted(expected_emails)

    if db_emails != expected_emails:
        print(
            f"[FAIL] User list mismatch.\nFound: {db_emails}\nExpected: {expected_emails}",
            file=sys.stderr,
        )
        return False
    print(f"[PASS] User list matches expected list.", file=sys.stderr)
    return True


def check_user_password(cur, email, expected_hash_password):
    cur.execute("SELECT password FROM public.users WHERE email = %s", (email,))
    result = cur.fetchone()
    if not result:
        print(f"[FAIL] Could not retrieve password hash for '{email}'", file=sys.stderr)
        return False

    stored_hash = result[0]
    if stored_hash == expected_hash_password:
        print(
            f"[PASS] Password for '{email}' matches expected password.", file=sys.stderr
        )
        return True
    else:
        print(
            f"[FAIL] Password for '{email}' does not match expected password.",
            file=sys.stderr,
        )
        return False


def check_notebook_count(cur, user_id, expected_count, email):
    cur.execute(
        """
        SELECT COUNT(*)
        FROM public.items i
        JOIN public.user_items ui ON i.id = ui.item_id
        WHERE i.jop_type = 1 AND ui.user_id = %s
    """,
        (user_id,),
    )
    count = cur.fetchone()[0]
    if count != expected_count:
        print(
            f"[FAIL] User '{email}' has {count} notebooks; expected {expected_count}.",
            file=sys.stderr,
        )
        return False
    print(f"[PASS] User '{email}' has correct notebook count.", file=sys.stderr)
    return True


def check_note_count(cur, user_id, expected_count, email):
    cur.execute(
        """
        SELECT COUNT(*)
        FROM public.items i
        JOIN public.user_items ui ON i.id = ui.item_id
        WHERE i.jop_type = 0 AND ui.user_id = %s
    """,
        (user_id,),
    )
    count = cur.fetchone()[0]
    if count != expected_count:
        print(
            f"[FAIL] User '{email}' has {count} notes; expected {expected_count}.",
            file=sys.stderr,
        )
        return False
    print(f"[PASS] User '{email}' has correct note count.", file=sys.stderr)
    return True


def check_notebook_names(cur, user_id, expected_names, email):
    cur.execute(
        """
        SELECT i.name
        FROM public.items i
        JOIN public.user_items ui ON i.id = ui.item_id
        WHERE i.jop_type = 1 AND ui.user_id = %s
    """,
        (user_id,),
    )
    db_names = sorted([row[0] for row in cur.fetchall()])
    expected_names = sorted(expected_names)
    if db_names != expected_names:
        print(
            f"[FAIL] Notebook names mismatch. Found: {db_names}, Expected: {expected_names}",
            file=sys.stderr,
        )
        return False
    print(f"[PASS] Notebook names match.", file=sys.stderr)
    return True


def check_notebook_ids(cur, user_id, expected_ids, email):
    cur.execute(
        """
        SELECT i.id
        FROM public.items i
        JOIN public.user_items ui ON i.id = ui.item_id
        WHERE i.jop_type = 1 AND ui.user_id = %s
    """,
        (user_id,),
    )
    db_ids = sorted([row[0] for row in cur.fetchall()])
    expected_ids = sorted(expected_ids)
    if db_ids != expected_ids:
        print(
            f"[FAIL] Notebook ids mismatch. Found: {db_ids}, Expected: {expected_ids}",
            file=sys.stderr,
        )
        return False
    print(f"[PASS] Notebook ids match.", file=sys.stderr)
    return True


def check_note_names(cur, user_id, expected_names, email):
    cur.execute(
        """
        SELECT i.name
        FROM public.items i
        JOIN public.user_items ui ON i.id = ui.item_id
        WHERE i.jop_type = 0 AND ui.user_id = %s
    """,
        (user_id,),
    )
    db_names = sorted([row[0] for row in cur.fetchall()])
    expected_names = sorted(expected_names)
    if db_names != expected_names:
        print(
            f"[FAIL] Note names mismatch. Found: {db_names}, Expected: {expected_names}",
            file=sys.stderr,
        )
        return False
    print(f"[PASS] Note names match.", file=sys.stderr)
    return True


def check_note_ids(cur, user_id, expected_ids, email):
    cur.execute(
        """
        SELECT i.id
        FROM public.items i
        JOIN public.user_items ui ON i.id = ui.item_id
        WHERE i.jop_type = 0 AND ui.user_id = %s
    """,
        (user_id,),
    )
    db_ids = sorted([row[0] for row in cur.fetchall()])
    expected_ids = sorted(expected_ids)
    if db_ids != expected_ids:
        print(
            f"[FAIL] Notebook ids mismatch. Found: {db_ids}, Expected: {expected_ids}",
            file=sys.stderr,
        )
        return False
    print(f"[PASS] Notebook ids match.", file=sys.stderr)
    return True


def check_note_contents(cur, user_id, expected_contents, email):
    cur.execute(
        """
        SELECT convert_from(i.content, 'UTF8')
        FROM public.items i
        JOIN public.user_items ui ON i.id = ui.item_id
        WHERE i.jop_type = 0 AND ui.user_id = %s
    """,
        (user_id,),
    )
    db_contents = sorted([row[0] for row in cur.fetchall()])
    expected_contents = sorted(expected_contents)
    if db_contents != expected_contents:
        print(
            f"[FAIL] Note contents mismatch.\nFound: {db_contents}\nExpected: {expected_contents}",
            file=sys.stderr,
        )
        return False
    print(f"[PASS] Note contents match.", file=sys.stderr)
    return True


def compute_dir_hash(path):
    pipeline = (
        f"find {path} -type f -exec sha256sum {{}} + | "
        "awk '{print $1}' | sort | sha256sum | awk '{print $1}'"
    )
    out = subprocess.check_output(["adb", "shell", pipeline], stderr=subprocess.STDOUT)
    return out.decode().strip()


def check_immutable_dirs():
    for directory, expected_hash in baseline.items():
        actual_hash = compute_dir_hash(directory)
        if actual_hash != expected_hash:
            print(
                f"[FAIL] {directory} hash mismatch (expected {expected_hash}, got {actual_hash})",
                file=sys.stderr,
            )
            return False
    print(f"[PASS] hashes match.", file=sys.stderr)
    return True


def check_user_data(dbname, user, password, port):
    conn = psycopg2.connect(
        dbname=dbname, user=user, password=password, host="localhost", port=port
    )
    cur = conn.cursor()
    all_passed = True

    results_summary = {}

    expected_emails = [config["email"] for config in USER_CONFIGS] + ["usera@localhost"]
    check_user = check_user_list(cur, expected_emails)
    results_summary["check_user_list"] = 1 if check_user else 0
    check_dirs = check_immutable_dirs()
    results_summary["check_immutable_dirs"] = 1 if check_dirs else 0
    if not check_user or not check_dirs:
        all_passed = False

    for config in USER_CONFIGS:
        email = config["email"]
        results_summary[email] = {}

        passed, user_id = check_user_exists(cur, email)
        results_summary[email]["check_user_exists"] = 1 if passed else 0

        if not passed:
            all_passed = False
            continue

        checks = {
            "check_user_password": check_user_password(cur, email, config["password"]),
            "check_notebook_count": check_notebook_count(
                cur, user_id, config["expected_notebook_count"], email
            ),
            "check_note_count": check_note_count(
                cur, user_id, config["expected_note_count"], email
            ),
            "check_notebook_names": check_notebook_names(
                cur, user_id, config["notebook_names"], email
            ),
            "check_notebook_ids": check_notebook_ids(
                cur, user_id, config["notebook_ids"], email
            ),
            "check_note_names": check_note_names(
                cur, user_id, config["note_names"], email
            ),
            "check_note_ids": check_note_ids(cur, user_id, config["note_ids"], email),
            "check_note_contents": check_note_contents(
                cur, user_id, config["note_contents"], email
            ),
        }

        for check_name, check_passed in checks.items():
            results_summary[email][check_name] = 1 if check_passed else 0
            if not check_passed:
                all_passed = False

    cur.close()
    conn.close()
    return all_passed, results_summary


if __name__ == "__main__":
    all_passed, results_summary = check_user_data(
        dbname="mydatabase", user="postgres", password="postgresPW", port=5432
    )

    print(json.dumps(results_summary))

    if all_passed:
        sys.exit(0)
    else:
        sys.exit(1)
