import sys
import subprocess

# Seeded data to check for existence
SEEDED_ROWS = {
    "subscriptions": [
        {"url": "https://youtube.com/channel/test1", "name": "Test Channel 1"},
        {"url": "https://youtube.com/channel/test2", "name": "Test Channel 2"}
    ],
    "streams": [
        {"url": "https://youtube.com/watch?v=video1", "title": "Test Video 1"},
        {"url": "https://youtube.com/watch?v=video2", "title": "Test Video 2"}
    ],
    "stream_history": [
        {"stream_id": 1, "repeat_count": 2},
        {"stream_id": 2, "repeat_count": 1}
    ],
    "feed_group": [
        {"name": "Test Feed Group"}
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

def run_adb_command(command):
    result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
    return result.stdout.strip() if result.returncode == 0 else None

def check_row_exists(table, conditions, db_path):
    where = " AND ".join([f"{k} = '{v}'" for k, v in conditions.items()])
    query = f"SELECT COUNT(*) FROM {table} WHERE {where};"
    result = run_adb_command(f'adb shell "run-as org.schabi.newpipe.debug.newplayer sqlite3 {db_path} \"{query}\""')
    try:
        return int(result) > 0
    except (TypeError, ValueError):
        return False

def check_integrity():
    """Check that all seeded data is still present in the database."""
    db_path = "/data/data/org.schabi.newpipe.debug.newplayer/databases/newpipe.db"

    # Check if database exists
    result = run_adb_command(f'adb shell "run-as org.schabi.newpipe.debug.newplayer test -f {db_path} && echo EXISTS"')
    if not result or "EXISTS" not in result:
        print("[FAIL] Database file does not exist.", file=sys.stderr)
        return 1

    all_passed = True
    for table, rows in SEEDED_ROWS.items():
        for row in rows:
            if not check_row_exists(table, row, db_path):
                print(f"[FAIL] Seeded row missing in {table}: {row}", file=sys.stderr)
                all_passed = False
    if all_passed:
        print("[PASS] All seeded data is present in the database.", file=sys.stderr)
        return 0
    else:
        return 1

if __name__ == "__main__":
    check_integrity() 