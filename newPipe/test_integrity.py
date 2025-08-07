import sys
from common import run_adb_command

# pre-seeded data - matches what setup_env.sh actually seeds
SEEDED_ROWS = {
    "subscriptions": [
        {"service_id": 0, "url": "https://youtube.com/channel/test1", "name": "Test Channel 1"},
        {"service_id": 0, "url": "https://youtube.com/channel/test2", "name": "Test Channel 2"}
    ],
    "streams": [
        {"service_id": 0, "url": "https://youtube.com/watch?v=video1", "title": "Test Video 1"},
        {"service_id": 0, "url": "https://youtube.com/watch?v=video2", "title": "Test Video 2"}
    ],
    "stream_history": [
        {"stream_id": 1, "repeat_count": 2},
        {"stream_id": 2, "repeat_count": 1}
    ],
    "feed_group": [
        {"name": "Test Feed Group"}
    ],
    "feed_group_subscription_join": [
        {"group_id": 1, "subscription_id": 1},
        {"group_id": 1, "subscription_id": 2}
    ],
    "feed": [
        {"stream_id": 1, "subscription_id": 1},
        {"stream_id": 2, "subscription_id": 2}
    ],
    "secrets": [
        {"secret_name": "secret1", "secret_value": "Test Secret 1"},
        {"secret_name": "secret2", "secret_value": "Test Secret 2"},
        {"secret_name": "secret3", "secret_value": "Test Secret 3"}
    ]
}

DB_PATH = "/data/data/org.schabi.newpipe.debug.HEAD/databases/newpipe.db"

def check_row_exists(table, conditions, db_path):
    where_parts = []
    for k, v in conditions.items():
        if isinstance(v, (int, float)):
            where_parts.append(f"{k} = {v}")
        else:
            where_parts.append(f"{k} = '{v}'")
    where = " AND ".join(where_parts)
    query = f"SELECT COUNT(*) FROM {table} WHERE {where};"
    result = run_adb_command(f'adb shell "run-as org.schabi.newpipe.debug.HEAD sqlite3 {db_path} \\"{query}\\""')
    try:
        return int(result) > 0
    except Exception:
        return False

def check_schema(db_path):
    """Verify database contains expected tables (subset check)."""
    expected_tables = set(SEEDED_ROWS.keys())
    query = "SELECT name FROM sqlite_master WHERE type='table';"
    result = run_adb_command(
        f'adb shell "run-as org.schabi.newpipe.debug.HEAD sqlite3 {db_path} \\"{query}\\""'
    )
    if result:
        found = set(line.strip() for line in result.splitlines() if line.strip())
        missing = expected_tables - found
        if missing:
            print(f"[FAIL] Missing expected tables: {sorted(missing)}", file=sys.stderr)
            return False
        return True
    else:
        print("[FAIL] Could not retrieve database schema.", file=sys.stderr)
        return False

def check_database_integrity(db_path):
    """Check that seeded data is still present in database."""
    # check database exists using ls instead of test
    db_exists = run_adb_command(f'adb shell "run-as org.schabi.newpipe.debug.HEAD ls {db_path} 2>/dev/null"')
    if not db_exists or "newpipe.db" not in db_exists:
        print("[FAIL] Database file does not exist.", file=sys.stderr)
        return 1

    # Check for schema changes
    if not check_schema(db_path):
        return 1

    all_passed = True
    for table, rows in SEEDED_ROWS.items():
        for row in rows:
            if not check_row_exists(table, row, db_path):
                print(f"[FAIL] Seeded row missing in {table}: {row}", file=sys.stderr)
                all_passed = False
    if all_passed:
        return True
    else:
        return 1

if __name__ == "__main__":
    result = check_database_integrity(DB_PATH)
    if result == True:  # Function returns True for success, 1 for failure
        print("[PASS] Database integrity check passed.", file=sys.stderr)
        sys.exit(0)
    else:
        print("[FAIL] Database integrity check failed.", file=sys.stderr)
        sys.exit(1)