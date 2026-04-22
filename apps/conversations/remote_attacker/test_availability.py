"""Conversations remote_attacker availability probe — STUB.

TODO: re-enable once synthetic redteam pipeline lands. Real checks
(XMPP port reachability, Prosody container running) are kept in git
history; un-stub by restoring the prior revision.
"""

import json
import sys

if __name__ == "__main__":
    print(json.dumps({"score": 1, "triggered": 0, "status": "stub"}))
    sys.exit(0)
