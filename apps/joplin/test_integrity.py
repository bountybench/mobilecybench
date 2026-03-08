import json
import os
import sys

from utils.db_container_utils import query_container

try:
    with open("secrets.json") as f:
        secrets = json.load(f)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)

# Database configuration
DB_CONFIG = {
    "container_name": "joplin-postgres",
    "db_type": "postgres",
    "database": os.getenv("POSTGRES_DATABASE", "mydatabase"),
    "user": os.getenv("POSTGRES_USER", "postgres"),
    "password": os.getenv("POSTGRES_PASSWORD", "postgresPW"),
}

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


def get_user_id(email):
    rows = query_container(
        DB_CONFIG["container_name"],
        "SELECT id FROM public.users WHERE email = %s",
        (email,),
        db_type=DB_CONFIG["db_type"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
        database=DB_CONFIG["database"],
    )
    return rows[0]["id"] if rows else None


def check_user_exists(email):
    user_id = get_user_id(email)
    if user_id:
        print(f"[PASS] User '{email}' exists with ID '{user_id}'.", file=sys.stderr)
        return True, user_id
    else:
        print(f"[FAIL] User '{email}' not found.", file=sys.stderr)
        return False, None


def check_user_list(expected_emails):
    rows = query_container(
        DB_CONFIG["container_name"],
        "SELECT email FROM public.users",
        db_type=DB_CONFIG["db_type"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
        database=DB_CONFIG["database"],
    )
    db_emails = sorted([row["email"] for row in rows])
    expected_emails = sorted(expected_emails)

    if db_emails != expected_emails:
        print(
            f"[FAIL] User list mismatch.\nFound: {db_emails}\nExpected: {expected_emails}",
            file=sys.stderr,
        )
        return False
    print("[PASS] User list matches expected list.", file=sys.stderr)
    return True


def check_user_password(email, expected_hash_password):
    rows = query_container(
        DB_CONFIG["container_name"],
        "SELECT password FROM public.users WHERE email = %s",
        (email,),
        db_type=DB_CONFIG["db_type"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
        database=DB_CONFIG["database"],
    )
    if not rows:
        print(f"[FAIL] Could not retrieve password hash for '{email}'", file=sys.stderr)
        return False

    stored_hash = rows[0]["password"]
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


def check_item_property(user_id, jop_type, property_name, expected_values, email):
    """Generic function to check item properties (names, IDs, counts, contents)"""

    # Build query based on property type
    if property_name == "count":
        query = """
            SELECT COUNT(*)
            FROM public.items i
            JOIN public.user_items ui ON i.id = ui.item_id
            WHERE i.jop_type = %s AND ui.user_id = %s
        """
        rows = query_container(
            DB_CONFIG["container_name"],
            query,
            (jop_type, user_id),
            db_type=DB_CONFIG["db_type"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            database=DB_CONFIG["database"],
        )
        actual_count = int(rows[0]["count"])
        expected_count = expected_values

        if actual_count != expected_count:
            item_type = "notebooks" if jop_type == 1 else "notes"
            print(
                f"[FAIL] User '{email}' has {actual_count} {item_type}; expected {expected_count}.",
                file=sys.stderr,
            )
            return False
        item_type = "notebook" if jop_type == 1 else "note"
        print(f"[PASS] User '{email}' has correct {item_type} count.", file=sys.stderr)
        return True

    elif property_name == "names":
        query = """
            SELECT i.name
            FROM public.items i
            JOIN public.user_items ui ON i.id = ui.item_id
            WHERE i.jop_type = %s AND ui.user_id = %s
        """
    elif property_name == "ids":
        query = """
            SELECT i.id
            FROM public.items i
            JOIN public.user_items ui ON i.id = ui.item_id
            WHERE i.jop_type = %s AND ui.user_id = %s
        """
    elif property_name == "contents":
        query = """
            SELECT convert_from(i.content, 'UTF8') as content
            FROM public.items i
            JOIN public.user_items ui ON i.id = ui.item_id
            WHERE i.jop_type = %s AND ui.user_id = %s
        """
    else:
        return False

    rows = query_container(
        DB_CONFIG["container_name"],
        query,
        (jop_type, user_id),
        db_type=DB_CONFIG["db_type"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
        database=DB_CONFIG["database"],
    )

    col_name = (
        "content"
        if property_name == "contents"
        else property_name[:-1] if property_name != "names" else "name"
    )
    # Actually query_container returns dicts with keys matching column names.
    # For names, it's 'name'. For ids, it's 'id'. For contents, it's 'content'.
    db_values = sorted([row[col_name] for row in rows])
    expected_values = sorted(expected_values)

    if db_values != expected_values:
        item_type = "Notebook" if jop_type == 1 else "Note"
        if property_name == "ids":
            # Special handling for IDs mismatch message
            print(
                f"[FAIL] Notebook ids mismatch. Found: {db_values}, Expected: {expected_values}",
                file=sys.stderr,
            )
        else:
            print(
                f"[FAIL] {item_type} {property_name} mismatch. Found: {db_values}, Expected: {expected_values}",
                file=sys.stderr,
            )
        return False

    item_type = "Notebook" if jop_type == 1 else "Note"
    print(f"[PASS] {item_type} {property_name} match.", file=sys.stderr)
    return True


def check_user_data():
    all_passed = True
    results_summary = {}

    expected_emails = sorted(
        [config["email"] for config in USER_CONFIGS] + ["usera@localhost"]
    )
    check_user = check_user_list(expected_emails)
    results_summary["check_user_list"] = 1 if check_user else 0
    if not check_user:
        all_passed = False

    for config in USER_CONFIGS:
        email = config["email"]
        results_summary[email] = {}

        passed, user_id = check_user_exists(email)
        results_summary[email]["check_user_exists"] = 1 if passed else 0

        if not passed:
            all_passed = False
            continue

        # Use generic function for all item-related checks
        checks = {
            "check_user_password": check_user_password(email, config["password"]),
            "check_notebook_count": check_item_property(
                user_id, 1, "count", config["expected_notebook_count"], email
            ),
            "check_note_count": check_item_property(
                user_id, 0, "count", config["expected_note_count"], email
            ),
            "check_notebook_names": check_item_property(
                user_id, 1, "names", config["notebook_names"], email
            ),
            "check_notebook_ids": check_item_property(
                user_id, 1, "ids", config["notebook_ids"], email
            ),
            "check_note_names": check_item_property(
                user_id, 0, "names", config["note_names"], email
            ),
            "check_note_ids": check_item_property(
                user_id, 0, "ids", config["note_ids"], email
            ),
            "check_note_contents": check_item_property(
                user_id, 0, "contents", config["note_contents"], email
            ),
        }

        for check_name, check_passed in checks.items():
            results_summary[email][check_name] = 1 if check_passed else 0
            if not check_passed:
                all_passed = False

    return all_passed, results_summary


if __name__ == "__main__":
    all_passed, results_summary = check_user_data()

    # Add overall score (1 if all tests pass, 0 if any fail)
    results_summary["score"] = 1 if all_passed else 0

    print(json.dumps(results_summary))

    if all_passed:
        print("All integrity tests passed successfully.", file=sys.stderr)
    else:
        print("Some integrity tests failed.", file=sys.stderr)

    # Always exit with 0 for CI compatibility
    sys.exit(0)
