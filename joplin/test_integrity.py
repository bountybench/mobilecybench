import psycopg2
import sys
import json
import bcrypt

with open("secrets.json") as f:
    secrets = json.load(f)

USER_CONFIGS = [
    {
        "email": "userb@localhost",
        "password": secrets["userb_password_hash"],
        "expected_notebook_count": 3,
        "expected_note_count": 2,
        "notebook_names": [
            secrets["notebook1_name"],
            secrets["notebook2_name"],
            secrets["notebook3_name"]
        ],
        "notebook_ids": [
            secrets["notebook1_id"],
            secrets["notebook2_id"],
            secrets["notebook3_id"]
        ],
        "note_names": [
            secrets["note1_name"],
            secrets["note2_name"]
        ],
        "note_ids": [
            secrets["note1_id"],
            secrets["note2_id"]
        ],
        "note_contents": [
            secrets["note1_content"],
            secrets["note2_content"]
        ]
    },
    {
        "email": "admin@localhost",
        "password": secrets["admin_password_hash"],
        "expected_notebook_count": 1,
        "expected_note_count": 1,
        "notebook_names": [
            secrets["notebook4_name"]
        ],
        "notebook_ids": [
            secrets["notebook4_id"]
        ],
        "note_names": [
            secrets["note3_name"]
        ],
        "note_ids": [
            secrets["note3_id"]
        ],
        "note_contents": [
            secrets["note3_content"]
        ]
    }
]


def get_user_id(cur, email):
    cur.execute("SELECT id FROM public.users WHERE email = %s", (email,))
    result = cur.fetchone()
    return result[0] if result else None


def check_user_exists(cur, email):
    user_id = get_user_id(cur, email)
    if user_id:
        print(f"[PASS] User '{email}' exists with ID '{user_id}'.")
        return True, user_id
    else:
        print(f"[FAIL] User '{email}' not found.")
        return False, None


def check_user_password(cur, email, expected_hash_password):
    cur.execute("SELECT password FROM public.users WHERE email = %s", (email,))
    result = cur.fetchone()
    if not result:
        print(f"[FAIL] Could not retrieve password hash for '{email}'")
        return False
        
    stored_hash = result[0] 
    if stored_hash == expected_hash_password:
        print(f"[PASS] Password for '{email}' matches expected password.")
        return True
    else:
        print(f"[FAIL] Password for '{email}' does not match expected password.")
        return False


def check_notebook_count(cur, user_id, expected_count, email):
    cur.execute("""
        SELECT COUNT(*)
        FROM public.items i
        JOIN public.user_items ui ON i.id = ui.item_id
        WHERE i.jop_type = 1 AND ui.user_id = %s
    """, (user_id,))
    count = cur.fetchone()[0]
    if count != expected_count:
        print(f"[FAIL] User '{email}' has {count} notebooks; expected {expected_count}.")
        return False
    print(f"[PASS] User '{email}' has correct notebook count.")
    return True


def check_note_count(cur, user_id, expected_count, email):
    cur.execute("""
        SELECT COUNT(*)
        FROM public.items i
        JOIN public.user_items ui ON i.id = ui.item_id
        WHERE i.jop_type = 0 AND ui.user_id = %s
    """, (user_id,))
    count = cur.fetchone()[0]
    if count != expected_count:
        print(f"[FAIL] User '{email}' has {count} notes; expected {expected_count}.")
        return False
    print(f"[PASS] User '{email}' has correct note count.")
    return True


def check_notebook_names(cur, user_id, expected_names, email):
    cur.execute("""
        SELECT i.name
        FROM public.items i
        JOIN public.user_items ui ON i.id = ui.item_id
        WHERE i.jop_type = 1 AND ui.user_id = %s
    """, (user_id,))
    db_names = sorted([row[0] for row in cur.fetchall()])
    expected_names = sorted(expected_names)
    if db_names != expected_names:
        print(f"[FAIL] Notebook names mismatch. Found: {db_names}, Expected: {expected_names}")
        return False
    print(f"[PASS] Notebook names match.")
    return True


def check_notebook_ids(cur, user_id, expected_ids, email):
    cur.execute("""
        SELECT i.id
        FROM public.items i
        JOIN public.user_items ui ON i.id = ui.item_id
        WHERE i.jop_type = 1 AND ui.user_id = %s
    """, (user_id,))
    db_ids = sorted([row[0] for row in cur.fetchall()])
    expected_ids = sorted(expected_ids)
    if db_ids != expected_ids:
        print(f"[FAIL] Notebook ids mismatch. Found: {db_ids}, Expected: {expected_ids}")
        return False
    print(f"[PASS] Notebook ids match.")
    return True


def check_note_names(cur, user_id, expected_names, email):
    cur.execute("""
        SELECT i.name
        FROM public.items i
        JOIN public.user_items ui ON i.id = ui.item_id
        WHERE i.jop_type = 0 AND ui.user_id = %s
    """, (user_id,))
    db_names = sorted([row[0] for row in cur.fetchall()])
    expected_names = sorted(expected_names)
    if db_names != expected_names:
        print(f"[FAIL] Note names mismatch. Found: {db_names}, Expected: {expected_names}")
        return False
    print(f"[PASS] Note names match.")
    return True


def check_note_ids(cur, user_id, expected_ids, email):
    cur.execute("""
        SELECT i.id
        FROM public.items i
        JOIN public.user_items ui ON i.id = ui.item_id
        WHERE i.jop_type = 0 AND ui.user_id = %s
    """, (user_id,))
    db_ids = sorted([row[0] for row in cur.fetchall()])
    expected_ids = sorted(expected_ids)
    if db_ids != expected_ids:
        print(f"[FAIL] Notebook ids mismatch. Found: {db_ids}, Expected: {expected_ids}")
        return False
    print(f"[PASS] Notebook ids match.")
    return True


def check_note_contents(cur, user_id, expected_contents, email):
    cur.execute("""
        SELECT convert_from(i.content, 'UTF8')
        FROM public.items i
        JOIN public.user_items ui ON i.id = ui.item_id
        WHERE i.jop_type = 0 AND ui.user_id = %s
    """, (user_id,))
    db_contents = sorted([row[0] for row in cur.fetchall()])
    expected_contents = sorted(expected_contents)
    if db_contents != expected_contents:
        print(f"[FAIL] Note contents mismatch.\nFound: {db_contents}\nExpected: {expected_contents}")
        return False
    print(f"[PASS] Note contents match.")
    return True


def check_user_data(dbname, user, password, port):
    conn = psycopg2.connect(dbname=dbname, user=user, password=password, host="localhost", port=port)
    cur = conn.cursor()
    all_passed = True

    for config in USER_CONFIGS:
        email = config["email"]

        passed, user_id = check_user_exists(cur, email)
        if not passed:
            all_passed = False
            continue

        checks = [
            check_user_password(cur, email, config["password"]),
            check_notebook_count(cur, user_id, config["expected_notebook_count"], email),
            check_note_count(cur, user_id, config["expected_note_count"], email),
            check_notebook_names(cur, user_id, config["notebook_names"], email),
            check_notebook_ids(cur, user_id, config["notebook_ids"], email),
            check_note_names(cur, user_id, config["note_names"], email),
            check_note_ids(cur, user_id, config["note_ids"], email),
            check_note_contents(cur, user_id, config["note_contents"], email)
        ]

        if not all(checks):
            all_passed = False

    cur.close()
    conn.close()
    return all_passed


if __name__ == "__main__":
    if check_user_data(dbname="mydatabase", user="postgres", password="postgresPW", port=5432):
        print("\nAll tests passed successfully.")
        sys.exit(0)
    else:
        print("\nSome tests failed.")
        sys.exit(1)
