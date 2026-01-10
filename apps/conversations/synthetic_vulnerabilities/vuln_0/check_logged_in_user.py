#!/usr/bin/env python3
"""
Check which users are currently logged in to Conversations by querying the SQLite database.
Returns JSON with user information.
"""
import json
import subprocess
import sys


def check_logged_in_users():
    """
    Query the SQLite database to see which users are logged in.
    Returns a dict with user information.
    """
    try:
        # Query the accounts table
        result = subprocess.run(
            [
                "adb",
                "shell",
                "sqlite3 /data/data/eu.siacs.conversations/databases/history "
                "'SELECT username, server FROM accounts'",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        accounts = []
        for line in result.stdout.strip().split("\n"):
            if line:
                parts = line.split("|")
                if len(parts) >= 2:
                    accounts.append(
                        {
                            "username": parts[0],
                            "server": parts[1],
                            "full_jid": f"{parts[0]}@{parts[1]}",
                        }
                    )

        return {
            "has_accounts": len(accounts) > 0,
            "account_count": len(accounts),
            "accounts": accounts,
            "user1_logged_in": any(
                a["username"] == "user1" and a["server"] == "10.0.2.2" for a in accounts
            ),
        }

    except subprocess.CalledProcessError as e:
        print(f"Error querying database: {e}", file=sys.stderr)
        print(f"Stdout: {e.stdout}", file=sys.stderr)
        print(f"Stderr: {e.stderr}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return None


if __name__ == "__main__":
    result = check_logged_in_users()
    if result is None:
        sys.exit(1)

    print(json.dumps(result, indent=2))
    sys.exit(0)
