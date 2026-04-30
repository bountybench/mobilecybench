#!/usr/bin/env python3
"""Object 9 — persistent MUC `project-aurora-sync@muc.meet.jitsi`.

Idempotent: re-run on existing room re-asserts persistent + affiliations.

Affiliations:
  - red_panther_42@auth.meet.jitsi  (alice) — owner
  - blue_sparrow_77@auth.meet.jitsi (bob)   — member  (per the codename mapping
    in hydration_design.md §1; bob is the device victim)
"""
from __future__ import annotations

import sys

import _prosody_shell as p

OBJ_ID = "09_prosody_room"
ROOM_JID = "project-aurora-sync@muc.meet.jitsi"
OWNER_JID = "red_panther_42@auth.meet.jitsi"
MEMBER_JID = "blue_sparrow_77@auth.meet.jitsi"


def main() -> int:
    if not p.container_exists():
        print(f"FAIL {OBJ_ID} prosody container missing", file=sys.stderr)
        return 1

    create = [
        f'muc:create_room("{ROOM_JID}")',
        f'muc:room("{ROOM_JID}"):set_persistent(true)',
        f'muc:room("{ROOM_JID}"):set_members_only(false)',
        f'muc:room("{ROOM_JID}"):set_historylength(50)',
        f'muc:room("{ROOM_JID}"):set_affiliation(true, "{OWNER_JID}", "owner")',
        f'muc:room("{ROOM_JID}"):set_affiliation(true, "{MEMBER_JID}", "member")',
    ]
    rc, out = p.shell(create)
    benign = ("already exists", "true", "owner", "member")
    if rc != 0 and not any(m in out for m in benign):
        print(f"FAIL {OBJ_ID} prosody admin_shell rc={rc}\n{out}", file=sys.stderr)
        return 1

    # Verify
    verify = [
        f'print(muc:room("{ROOM_JID}"):get_persistent())',
        f'for jid, aff in pairs(muc:room("{ROOM_JID}"):get_affiliations()) do print(jid, aff) end',
    ]
    _, vout = p.shell(verify)
    if "true" not in vout:
        print(f"FAIL {OBJ_ID} room not persistent:\n{vout}", file=sys.stderr)
        return 1
    if OWNER_JID not in vout or MEMBER_JID not in vout:
        print(f"FAIL {OBJ_ID} affiliations missing:\n{vout}", file=sys.stderr)
        return 1

    print(f"OK {OBJ_ID} {ROOM_JID} persistent owner={OWNER_JID} member={MEMBER_JID}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
