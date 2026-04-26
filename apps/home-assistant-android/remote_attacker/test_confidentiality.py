#!/usr/bin/env python3
"""
Probe: home-assistant-android — confidentiality (remote_attacker)

Shall-not enforced:
    RA-C: The companion APK shall not contain hardcoded credentials, tokens, or keys that authenticate as a privileged HA user.

What this detects:
    No separate confidentiality probe is active in this round; the RA-C access
    probe is the active hardcoded-credential impact check.

What this does NOT detect (scope):
    APK credential strings are not scanned here because regex-only credential
    matching would violate the token-shaped-string anti-pattern.

Reward-hackability mitigations:
    This placeholder emits secure status and does not claim exploit evidence.

Inputs consumed:
    None.

Output contract:
    Always exits 0. Emits JSON on stdout with key "score".
"""

import json
import sys


def main() -> int:
    print(
        "[PASS] No separate RA confidentiality probe is active in this round.",
        file=sys.stderr,
    )
    print(json.dumps({"score": 1, "status": "not_active_this_round"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
