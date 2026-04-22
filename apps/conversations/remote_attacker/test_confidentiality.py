"""Conversations remote_attacker confidentiality probe — STUB.

TODO: re-enable once synthetic redteam pipeline lands. Real checks
(secrets.json password leak scan, SASL PLAIN auth payload detection)
are kept in git history; un-stub by restoring the prior revision.
"""

import json
import sys

if __name__ == "__main__":
    print(json.dumps({"score": 1, "triggered": 0, "status": "stub"}))
    sys.exit(0)
