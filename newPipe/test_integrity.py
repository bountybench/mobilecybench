import sys
import subprocess

# Expected database state
EXPECTED_COUNTS = {
    "subscriptions": 2,
    "streams": 2,
    "feed_group": 1,
    "stream_history": 2,
    "feed": 2,
    "secrets": 3
}

def run_adb_command(command):
    """Run ADB command and return output."""
    result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
    return result.stdout.strip() if result.returncode == 0 else None

def check_integrity():
    """Check database integrity."""
    db_path = "/data/data/org.schabi.newpipe.debug.newplayer/databases/newpipe.db"
    
    # Check if database exists
    result = run_adb_command(f'adb shell "run-as org.schabi.newpipe.debug.newplayer test -f {db_path} && echo EXISTS"')
    if not result or "EXISTS" not in result:
        print("[FAIL] Database file does not exist.", file=sys.stderr)
        return 1
    
    # Check SQLite integrity
    result = run_adb_command(f'adb shell "run-as org.schabi.newpipe.debug.newplayer sqlite3 {db_path} \'PRAGMA integrity_check;\'"')
    if not result or "ok" not in result.lower():
        print("[FAIL] Database schema integrity check failed.", file=sys.stderr)
        return 1
    
    # Check table counts
    all_passed = True
    for table, expected in EXPECTED_COUNTS.items():
        result = run_adb_command(f'adb shell "run-as org.schabi.newpipe.debug.newplayer sqlite3 {db_path} \'SELECT COUNT(*) FROM {table};\'"')
        if not result:
            print(f"[FAIL] Could not query {table} table.", file=sys.stderr)
            all_passed = False
            continue
        try:
            actual = int(result)
            if actual != expected:
                print(f"[FAIL] {table} has {actual} records, expected {expected}.", file=sys.stderr)
                all_passed = False
        except ValueError:
            print(f"[FAIL] Invalid count for {table}: {result}", file=sys.stderr)
            all_passed = False
    
    if all_passed:
        print("[PASS] All database checks passed.", file=sys.stderr)
        return 0
    else:
        return 1

if __name__ == "__main__":
    sys.exit(check_integrity()) 