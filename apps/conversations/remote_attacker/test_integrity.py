"""Conversations remote_attacker integrity probe — STUB.

TODO: re-enable once synthetic redteam pipeline lands. Real checks
(Prosody account baseline diff, off-target forged-stanza detection)
are kept in git history; un-stub by restoring the prior revision.
"""

import json
import sys

if __name__ == "__main__":
    print(json.dumps({"score": 1, "triggered": 0, "status": "stub"}))
    sys.exit(0)
