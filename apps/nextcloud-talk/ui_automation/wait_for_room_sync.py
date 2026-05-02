#!/usr/bin/env python3
"""Block until Talk's encrypted Room DB shows the post-login expected
room set, working around the race between login.py returning ('Main
screen reached' = UI ready) and Talk's background room-sync RPC
populating the Conversations table.

Without this wait, anything that runs immediately after prepare_victim.sh
and depends on a populated DB — vuln_scenarios/vuln_scenario_1/vuln.sh
killing the server, conversations_shape_intact reading rows — can win
the race against Talk's sync and observe an empty table.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import probe_lib as pl  # noqa: E402

DEADLINE_S = 60
INTERVAL_S = 2


def main() -> int:
    start = time.time()
    last_seen: object = "no rows yet"
    while time.time() - start < DEADLINE_S:
        try:
            rows = pl.read_conversations()
            names = {r.get("name", "") for r in rows}
            if names >= pl.CONVERSATION_NAMES_EXPECTED:
                print(
                    f"[wait_for_room_sync] OK after {time.time() - start:.1f}s "
                    f"({len(rows)} rooms)",
                    file=sys.stderr,
                )
                return 0
            last_seen = names
        except pl.ProbeError as e:
            last_seen = f"DB not ready: {e}"
        time.sleep(INTERVAL_S)
    print(
        f"[wait_for_room_sync] TIMEOUT after {DEADLINE_S}s; last seen: {last_seen}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
