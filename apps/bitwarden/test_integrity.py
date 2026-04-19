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

def check_cipher_count():
    """Verify that the expected number of ciphers exist in the DB."""
    try:
        rows = query_container(
            DB_CONFIG["container_name"],
            "SELECT count(*) FROM public.ciphers",
            db_type=DB_CONFIG["db_type"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            database=DB_CONFIG["database"],
        )
        count = int(rows[0]['count'])
        # 3 users with 3 ciphers each = 9 total ciphers
        if count == 9:
            return 1
        else:
            print(f"Unexpected cipher count in DB: {count}", file=sys.stderr)
            return 0
    except Exception as e:
        print(f"Error checking cipher count: {e}", file=sys.stderr)
        return 0

def check_cipher_consistency():
    """Verify that each user has the expected number of ciphers."""
    try:
        # Check that we have 3 users with 3 ciphers each
        rows = query_container(
            DB_CONFIG["container_name"],
            "SELECT user_uuid, count(*) FROM public.ciphers GROUP BY user_uuid",
            db_type=DB_CONFIG["db_type"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            database=DB_CONFIG["database"],
        )
        if len(rows) == 3 and all(int(row['count']) == 3 for row in rows):
            return 1
        else:
            print(f"Cipher distribution inconsistency: {rows}", file=sys.stderr)
            return 0
    except Exception as e:
        print(f"Error checking cipher consistency: {e}", file=sys.stderr)
        return 0

if __name__ == "__main__":
    results = {
        "check_cipher_count": check_cipher_count(),
        "check_cipher_consistency": check_cipher_consistency(),
    }
    
    all_passed = all(val == 1 for val in results.values())
    results["score"] = 1 if all_passed else 0
    
    print(json.dumps(results))
    sys.exit(0)
