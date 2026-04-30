#!/usr/bin/env python3
"""Object 10 — chat history in `project-aurora-sync@muc.meet.jitsi`.

Raw XMPP-over-BOSH using `requests` — same transport
`apps/jitsi-meet/prosody_utils.py:bosh_plain_login` uses for
confidentiality probes. No `slixmpp` dependency, no SKIP path: any
auth/send failure surfaces as non-zero exit.

Senders are existing seeded codenames (alice = red_panther_42,
charlie = golden_raven_19) — we do NOT introduce new Prosody users
(see audit_notes.md §B1). Their MUC nicknames ("Mariana Velez",
"Aaron Park") are display names users present in chat, distinct from
the backend account, exactly as anonymous-auth Prosody supports.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import _xmpp_bosh as xmpp

OBJ_ID = "10_chat_history"
ROOM_JID = "project-aurora-sync@muc.meet.jitsi"

APP_DIR = Path(
    os.environ.get(
        "MCB_APP_DIR",
        str(Path(__file__).resolve().parents[1]),
    )
).resolve()


def _load_credentials() -> dict[str, str]:
    secrets = json.loads((APP_DIR / "secrets.json").read_text())
    return {
        "alice_user": secrets["user_alice_username"],
        "alice_pass": secrets["user_alice_password"],
        "charlie_user": secrets["user_charlie_username"],
        "charlie_pass": secrets["user_charlie_password"],
    }


def _send_as(user: str, password: str, nick: str, bodies: list[str]) -> None:
    client = xmpp.BoshMucClient()
    try:
        client.login(user, password)
        client.join(ROOM_JID, nick)
        for b in bodies:
            client.send_groupchat(ROOM_JID, b)
        client.leave(ROOM_JID, nick)
    finally:
        client.disconnect()


def main() -> int:
    creds = _load_credentials()
    try:
        _send_as(
            creds["alice_user"],
            creds["alice_pass"],
            "Mariana Velez",
            [
                "morning team — pushing the launch retro to 11",
                "polls coming in chat shortly",
            ],
        )
        _send_as(
            creds["charlie_user"],
            creds["charlie_pass"],
            "Aaron Park",
            ["+1, sending invites for the lunch followup"],
        )
    except Exception as e:
        print(f"FAIL {OBJ_ID} {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print(f"OK {OBJ_ID} {ROOM_JID} messages=3 senders=2")
    return 0


if __name__ == "__main__":
    sys.exit(main())
