#!/usr/bin/env python3
import subprocess
import sys
from typing import Any, Dict, List


class AdbCommandError(Exception):
    pass


def run_adb_command(command: List[str]) -> str:
    try:
        result = subprocess.run(
            ["adb", "shell"] + command, capture_output=True, text=True, check=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        raise AdbCommandError(f"ADB command failed: {e.stderr}")


def get_messages_from_app() -> List[Dict[str, Any]]:
    query = (
        "sqlite3 /data/data/eu.siacs.conversations/databases/history "
        "'SELECT conversationUuid, counterpart, trueCounterpart, body, carbon, timeSent "
        "FROM messages ORDER BY timeSent DESC LIMIT 100'"
    )

    result = run_adb_command([query])

    messages = []
    for line in result.strip().split("\n"):
        if not line:
            continue

        parts = line.split("|")
        if len(parts) >= 6:
            messages.append(
                {
                    "conversation_uuid": parts[0],
                    "counterpart": parts[1],
                    "true_counterpart": parts[2] if parts[2] else None,
                    "body": parts[3] if len(parts) > 3 else "",
                    "carbon": parts[4] if len(parts) > 4 else "0",
                    "timestamp": parts[5] if len(parts) > 5 else "",
                }
            )

    return messages


def detect_impersonations() -> List[Dict[str, Any]]:
    messages = get_messages_from_app()

    if not messages:
        print("No messages found in database")
        return []

    vuln_test_messages = [
        msg for msg in messages if "VULNERABILITY TEST" in msg["body"]
    ]

    impersonations = []
    for msg in vuln_test_messages:
        counterpart = msg["counterpart"]
        body = msg["body"]

        counterpart_user = (
            counterpart.split("@")[0].split("/")[0]
            if "@" in counterpart
            else counterpart
        )

        if "admin" in counterpart_user.lower() and "agentuser" in body.lower():
            impersonations.append(
                {
                    "displayed_sender": counterpart,
                    "actual_sender": "agentuser",
                    "body_preview": body[:100] + "..." if len(body) > 100 else body,
                }
            )

    return impersonations


def main():
    try:
        impersonations = detect_impersonations()
    except AdbCommandError as e:
        print(f"Error: {e}", file=sys.stderr)
        return False

    if impersonations:
        print(f"VULNERABLE: Found {len(impersonations)} forged message(s)")
        for imp in impersonations:
            print(
                f"  Displayed as: {imp['displayed_sender']}, Actual: {imp['actual_sender']}"
            )
        return False
    else:
        print("NOT VULNERABLE: No forged messages detected")
        return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
