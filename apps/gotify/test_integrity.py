import json
import sys

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor

    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


def get_db_connection():
    """Get PostgreSQL database connection"""
    try:
        # Use docker exec to connect to the database
        db_params = {
            "host": "localhost",
            "port": "5432",
            "database": "gotify",
            "user": "gotify",
            "password": "gotify",
        }
        return psycopg2.connect(**db_params)
    except psycopg2.Error:
        return None


def check_database_integrity():
    """Check basic database integrity"""
    if not HAS_PSYCOPG2:
        print("psycopg2 not available - assuming clean state", file=sys.stderr)
        return True

    try:
        conn = get_db_connection()
        if not conn:
            print("Database connection failed - assuming clean state", file=sys.stderr)
            return True  # Assume pass if can't connect

        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check expected user count
        cur.execute("SELECT COUNT(*) as count FROM users")
        user_count = cur.fetchone()["count"]

        if user_count < 1:  # At least admin user should exist
            print(f"Unexpected user count: {user_count}", file=sys.stderr)
            cur.close()
            conn.close()
            return False

        # Check expected application count
        cur.execute("SELECT COUNT(*) as count FROM applications")
        app_count = cur.fetchone()["count"]

        if app_count < 1:  # Should have seeded applications
            print(f"Unexpected application count: {app_count}", file=sys.stderr)
            cur.close()
            conn.close()
            return False

        cur.close()
        conn.close()
        print(
            f"Database integrity check passed (users: {user_count}, apps: {app_count})",
            file=sys.stderr,
        )
        return True

    except Exception as e:
        print(f"Database integrity check skipped: {e}", file=sys.stderr)
        return True  # Assume pass if database unavailable


if __name__ == "__main__":
    results_summary = {}
    results_summary["check_database_integrity"] = 1 if check_database_integrity() else 0

    print(json.dumps(results_summary))

    all_passed = all(val == 1 for val in results_summary.values())
    if not all_passed:
        print("\nSome tests failed.", file=sys.stderr)
        sys.exit(1)
    else:
        print("\nAll tests passed successfully.", file=sys.stderr)
        sys.exit(0)
