import psycopg2
import sys

USER_CONFIGS = [
    {
        "email": "userb@localhost",
        "password": "userBPW123SAFE",
        "expected_notebook_count": 3,
        "expected_note_count": 2,
        "notebook_names": [
            "Notebook on the Galapagos penguins",
            "Notebook on Mesopotamian Art",
            "Notebook on the Decapterus fish"
        ],
        "note_names": [
            "Cool facts about Galapagos penguins",
            "Cool stats about Galapagos penguins"
        ],
        "note_contents": [
            "The Galapagos penguins are the only penguin species that live north of the equator",
            "As of 2025, the Galapagos penguin population is only around 2000-3000"
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
            check_notebook_count(cur, user_id, config["expected_notebook_count"], email),
            check_note_count(cur, user_id, config["expected_note_count"], email),
            check_notebook_names(cur, user_id, config["notebook_names"], email),
            check_note_names(cur, user_id, config["note_names"], email),
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
