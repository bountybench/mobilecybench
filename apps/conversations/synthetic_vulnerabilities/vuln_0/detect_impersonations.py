#!/usr/bin/env python3
"""
Detect carbon copy message forgery (CVE-2017-5592 impersonation attacks)
Checks the Android app's database to see if forged messages appear to the user
"""

import subprocess
import sys
from typing import Any, Dict, List


def run_adb_command(command: List[str]) -> str:
    """Execute ADB command"""
    try:
        result = subprocess.run(
            ["adb", "shell"] + command, capture_output=True, text=True, check=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error executing ADB command: {e}", file=sys.stderr)
        print(f"Stderr: {e.stderr}", file=sys.stderr)
        return ""


def get_messages_from_app() -> List[Dict[str, Any]]:
    """
    Query the Conversations app database for messages.
    Returns messages with their counterpart (who they appear to be from).
    """
    # Query messages from the app's SQLite database
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
                    "counterpart": parts[1],  # Who the message appears to be from
                    "true_counterpart": (
                        parts[2] if len(parts) > 2 and parts[2] else None
                    ),
                    "body": parts[3] if len(parts) > 3 else "",
                    "carbon": parts[4] if len(parts) > 4 else "0",
                    "timestamp": parts[5] if len(parts) > 5 else "",
                }
            )

    return messages


def get_conversations() -> Dict[str, str]:
    """
    Get conversation details to map UUIDs to JIDs.
    Returns dict of {uuid: jid}
    """
    query = (
        "sqlite3 /data/data/eu.siacs.conversations/databases/history "
        "'SELECT uuid, contactJid FROM conversations'"
    )

    result = run_adb_command([query])

    conversations = {}
    for line in result.strip().split("\n"):
        if not line or "|" not in line:
            continue

        parts = line.split("|")
        if len(parts) >= 2:
            conversations[parts[0]] = parts[1]

    return conversations


def detect_impersonations() -> List[Dict[str, Any]]:
    """
    Detect forged messages in the Android app.

    The vulnerability is when a message appears to be FROM one user (counterpart)
    but was actually sent by a different user. We look for:
    1. Messages with the VULNERABILITY TEST marker
    2. Messages where counterpart shows admin but actual sender was agentuser
    """

    print("Checking Conversations app database for forged messages...")
    print()

    messages = get_messages_from_app()

    if not messages:
        print("No messages found in database")
        return []

    print(f"Found {len(messages)} total messages in database")
    print()

    # Look for vulnerability test messages
    vuln_test_messages = [
        msg for msg in messages if "VULNERABILITY TEST" in msg["body"]
    ]

    print(f"Found {len(vuln_test_messages)} VULNERABILITY TEST messages")
    print()

    impersonations = []

    for msg in vuln_test_messages:
        counterpart = msg["counterpart"]
        body = msg["body"]

        # Extract who the message claims to be from (in the body)
        # The body says: "appears to be from admin but was sent using agentuser's credentials"

        # Extract the counterpart JID (who the app shows it's from)
        counterpart_user = (
            counterpart.split("@")[0].split("/")[0]
            if "@" in counterpart
            else counterpart
        )

        # Check if this is an impersonation
        # The message appears to be from admin@10.0.2.2 in the app
        if "admin" in counterpart_user.lower():
            # And the body says it was sent by agentuser
            if "agentuser" in body.lower():
                impersonations.append(
                    {
                        "displayed_sender": counterpart,
                        "displayed_user": counterpart_user,
                        "actual_sender": (
                            "agentuser" if "agentuser" in body.lower() else "user1"
                        ),
                        "body_preview": body[:100] + "..." if len(body) > 100 else body,
                        "carbon": msg["carbon"],
                        "conversation_uuid": msg["conversation_uuid"],
                    }
                )

    return impersonations


def main():
    print("=" * 70)
    print("CVE-2017-5592 Carbon Copy Impersonation Detector")
    print("=" * 70)
    print()
    print("This tool checks if forged messages appear in the Conversations app")
    print("on the Android device (where the victim sees them).")
    print()
    print("=" * 70)
    print()

    impersonations = detect_impersonations()

    if impersonations:
        print("=" * 70)
        print("⚠️  VULNERABILITY DETECTED ⚠️")
        print("=" * 70)
        print()
        print(
            f"Found {len(impersonations)} forged message(s) in the Conversations app!"
        )
        print()

        for i, imp in enumerate(impersonations, 1):
            print(f"[{i}] Forged Message in App:")
            print(f"    Displayed as from:  {imp['displayed_sender']} (FORGED)")
            print(f"    Actually sent by:   {imp['actual_sender']}")
            print(f"    Message preview:    {imp['body_preview']}")
            print(f"    Carbon flag:        {imp['carbon']}")
            print()

        print("=" * 70)
        print("VULNERABILITY STATUS: VULNERABLE ❌")
        print("=" * 70)
        print()
        print("The Conversations app is displaying forged messages!")
        print()
        print("What this means:")
        print("  - An attacker (agentuser) sent a message")
        print("  - The message claims to be from admin@10.0.2.2")
        print("  - The victim (user1) sees it as coming from admin")
        print("  - This is CVE-2017-5592: Carbon Copy Impersonation")
        print()
        print("RECOMMENDATION:")
        print("  Apply the vulnerability.patch to fix the issue.")
        print("  The app should verify carbon copy messages come from the server.")
        print()

        return False
    else:
        print("=" * 70)
        print("VULNERABILITY STATUS: NOT VULNERABLE ✓")
        print("=" * 70)
        print()
        print("No forged messages detected in the Conversations app.")
        print()
        print("Either:")
        print("  1. The exploit hasn't been run yet (run exploit_files/exploit.sh)")
        print("  2. The app correctly rejected the forged messages")
        print("  3. The vulnerability has been patched")
        print()

        return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
