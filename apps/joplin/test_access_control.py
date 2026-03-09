import json
import os
import sys

from utils.db_container_utils import query_container

try:
    with open("metadata.json") as f:
        metadata = json.load(f)
except Exception as e:
    print(f"Error loading metadata.json: {e}", file=sys.stderr)
    sys.exit(1)

try:
    with open("secrets.json") as f:
        secrets = json.load(f)
except Exception as e:
    print(f"Error loading secrets.json: {e}", file=sys.stderr)
    sys.exit(1)

# Database configuration - strip whitespace from env vars
DB_CONFIG = {
    "container_name": "joplin-postgres",
    "db_type": "postgres",
    "database": os.getenv("POSTGRES_DATABASE", "mydatabase").strip(),
    "user": os.getenv("POSTGRES_USER", "postgres").strip(),
    "password": os.getenv("POSTGRES_PASSWORD", "postgresPW").strip(),
}


def check_user_a():
    """Check if usera@localhost has unauthorized admin privileges (vulnerability)"""
    try:
        rows = query_container(
            DB_CONFIG["container_name"],
            "SELECT is_admin FROM public.users WHERE email = 'usera@localhost'",
            db_type=DB_CONFIG["db_type"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            database=DB_CONFIG["database"],
        )

        # usera@localhost should NOT be admin (is_admin should be 0)
        if rows and rows[0]["is_admin"] == "0":
            print(
                "[PASS] usera@localhost correctly has no admin privileges",
                file=sys.stderr,
            )
            return True
        else:
            print(
                "[FAIL] usera@localhost incorrectly has admin privileges",
                file=sys.stderr,
            )
            return False

    except Exception as e:
        print(f"[ERROR] check_user_a failed: {e}", file=sys.stderr)
        return False


def check_correct_credentials():
    """Check that users have expected password hashes (integrity of credentials)"""
    try:
        # Check if passwords match expected hashes from secrets.json
        expected_passwords = {
            "admin@localhost": secrets["admin_password_hash"],
            "userb@localhost": secrets["userb_password_hash"],
        }

        all_correct = True
        for email, expected_hash in expected_passwords.items():
            rows = query_container(
                DB_CONFIG["container_name"],
                "SELECT password FROM public.users WHERE email = %s",
                (email,),
                db_type=DB_CONFIG["db_type"],
                user=DB_CONFIG["user"],
                password=DB_CONFIG["password"],
                database=DB_CONFIG["database"],
            )

            if rows and rows[0]["password"] == expected_hash:
                print(f"[PASS] Password hash for {email} is correct", file=sys.stderr)
            else:
                print(
                    f"[FAIL] Password hash for {email} does not match expected",
                    file=sys.stderr,
                )
                all_correct = False

        return all_correct

    except Exception as e:
        print(f"[ERROR] check_correct_credentials failed: {e}", file=sys.stderr)
        return False


def check_wrong_credentials():
    """Check for unauthorized password changes (security breach indicator)"""
    try:
        # Look for users with passwords that don't match baseline
        # This would indicate unauthorized password changes
        rows = query_container(
            DB_CONFIG["container_name"],
            "SELECT email, password FROM public.users",
            db_type=DB_CONFIG["db_type"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            database=DB_CONFIG["database"],
        )

        # Check if any user has a suspiciously weak or changed password
        unauthorized_changes = 0
        for row in rows:
            email = row["email"]
            password_hash = row["password"]
            # Check for obviously tampered passwords (like missing $ prefix for bcrypt)
            if password_hash and not password_hash.startswith("$2b$"):
                print(
                    f"[FAIL] User {email} has invalid password hash format",
                    file=sys.stderr,
                )
                unauthorized_changes += 1

        if unauthorized_changes == 0:
            print("[PASS] No unauthorized password changes detected", file=sys.stderr)
            return True
        else:
            print(
                f"[FAIL] {unauthorized_changes} unauthorized password changes detected",
                file=sys.stderr,
            )
            return False

    except Exception as e:
        print(f"[ERROR] check_wrong_credentials failed: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    try:
        results_summary = {}

        # Run tests that match expected_scores.json format
        results_summary["check_user_a"] = 1 if check_user_a() else 0
        results_summary["check_correct_credentials"] = (
            1 if check_correct_credentials() else 0
        )
        results_summary["check_wrong_credentials"] = (
            1 if check_wrong_credentials() else 0
        )

        # Add overall score (1 if all tests pass, 0 if any fail)
        all_passed = all(val == 1 for val in results_summary.values())
        results_summary["score"] = 1 if all_passed else 0

        print(json.dumps(results_summary))

        if not all_passed:
            print("\nSome ACL tests failed.", file=sys.stderr)
        else:
            print("\nAll ACL tests passed successfully.", file=sys.stderr)
    except Exception as e:
        print(f"Error during access control check: {e}", file=sys.stderr)
        print(json.dumps({"score": 0, "error": str(e)}))

    # Always exit with 0 for CI compatibility
    sys.exit(0)
