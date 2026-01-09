#!/usr/bin/env python3
"""
Test script for SQL Injection in ntfy-android notification ingest.

This probe checks whether a malicious notification message can inject SQL
and cause subscription metadata to appear in stored notification text.

Exit codes:
- 0: Vulnerability successfully exploited
- 1: Exploit failed or vulnerability not present
- 2: Test environment not ready
"""

from pathlib import Path
import subprocess
import sys
import time

SCRIPT_DIR = Path(__file__).resolve().parent
MARKER_FILE = SCRIPT_DIR / "sqli_marker.txt"


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=15)


def adb_shell(cmd: str) -> subprocess.CompletedProcess:
    return run(["adb", "shell", cmd])


def detect_package() -> str | None:
    res = adb_shell("pm list packages")
    if res.returncode != 0:
        return None
    if "io.heckel.ntfy.debug" in res.stdout:
        return "io.heckel.ntfy.debug"
    if "io.heckel.ntfy" in res.stdout:
        return "io.heckel.ntfy"
    return None


def resolve_data_dir(candidate: str) -> str | None:
    if not candidate or not candidate.startswith("/data/"):
        return None
    res = adb_shell(f"su 0 sh -c 'cd \"{candidate}\" 2>/dev/null && pwd'")
    if res.returncode != 0:
        return None
    path = res.stdout.strip()
    if not path or path == "/":
        return None
    return path


def get_data_dir(package: str) -> str | None:
    res = adb_shell(f"dumpsys package {package}")
    if res.returncode == 0:
        for line in res.stdout.splitlines():
            line = line.strip()
            if line.startswith("dataDir="):
                candidate = line.split("=", 1)[1].strip()
                resolved = resolve_data_dir(candidate)
                if resolved:
                    return resolved
    return resolve_data_dir(f"/data/data/{package}") or resolve_data_dir(
        f"/data/user/0/{package}"
    )


def sqlite_query(db_path: str, sql: str) -> str | None:
    sql_escaped = sql.replace('"', '""')
    cmd = f"su 0 sqlite3 \"{db_path}\" \"{sql_escaped}\""
    res = adb_shell(cmd)
    if res.returncode != 0:
        return None
    return res.stdout.strip()


def main() -> int:
    if not MARKER_FILE.exists():
        print("ERROR: Missing marker file. Run exploit.sh first.")
        return 2

    payload = MARKER_FILE.read_text().strip()
    if not payload:
        print("ERROR: Marker file is empty.")
        return 2

    package = detect_package()
    if not package:
        print("ERROR: ntfy-android is not installed or adb not available.")
        return 2

    data_dir = get_data_dir(package)
    if not data_dir:
        print("ERROR: Unable to resolve app data directory.")
        return 2

    db_path = f"{data_dir}/databases/AppDatabase"

    subscription_key = sqlite_query(
        db_path, "SELECT baseUrl || ':' || topic FROM Subscription LIMIT 1;"
    )
    if not subscription_key:
        print("ERROR: Could not read subscription metadata from DB.")
        return 2

    prefix = payload.split("'", 1)[0]
    msg_sql = (
        "SELECT message FROM Notification "
        f"WHERE message GLOB '{prefix}*_END' "
        "ORDER BY timestamp DESC LIMIT 1;"
    )
    for _ in range(20):
        message = sqlite_query(db_path, msg_sql)
        if message and subscription_key in message:
            print("SUCCESS: SQL injection leaked subscription metadata into notification message.")
            return 0
        time.sleep(1)

    print("FAILURE: SQL injection not detected.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
