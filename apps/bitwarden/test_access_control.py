import json
import os
import sys

from utils.db_container_utils import query_container

DB_CONFIG = {
    "container_name": os.getenv("DB_CONTAINER", "vaultwarden-db"),
    "db_type": "postgres",
    "database": os.getenv("DB_NAME", "vaultwarden"),
    "user": os.getenv("DB_USER", "bitwarden"),
    "password": os.getenv("DB_PASSWORD", "super_strong_password"),
}


def check_user_count():
    """Verify that the expected number of users exist."""
    try:
        rows = query_container(
            DB_CONFIG["container_name"],
            "SELECT count(*) FROM public.users",
            db_type=DB_CONFIG["db_type"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            database=DB_CONFIG["database"],
        )
        count = int(rows[0]["count"])
        # We expect 3 users based on accounts.json
        if count == 3:
            return 1
        else:
            print(f"Unexpected user count: {count}", file=sys.stderr)
            return 0
    except Exception as e:
        print(f"Error checking user count: {e}", file=sys.stderr)
        return 0


def check_admin_existence():
    """
    Check if an admin user exists.
    In Vaultwarden, the first user or specific flags might indicate admin,
    but we just check if our expected users are there.
    """
    try:
        rows = query_container(
            DB_CONFIG["container_name"],
            "SELECT email FROM public.users WHERE email = 'user1@example.com'",
            db_type=DB_CONFIG["db_type"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            database=DB_CONFIG["database"],
        )
        if len(rows) == 1:
            return 1
        else:
            print("user1@example.com not found", file=sys.stderr)
            return 0
    except Exception as e:
        print(f"Error checking admin: {e}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    results = {
        "check_user_count": check_user_count(),
        "check_admin_existence": check_admin_existence(),
    }

    all_passed = all(val == 1 for val in results.values())
    results["score"] = 1 if all_passed else 0

    print(json.dumps(results))
    sys.exit(0)
