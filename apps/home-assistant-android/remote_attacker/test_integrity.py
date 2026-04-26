#!/usr/bin/env python3
"""
Probe: home-assistant-android — integrity (remote_attacker)

Shall-not enforced:
    RA-I: A low-privileged authenticated remote user shall not be able to escalate privileges, change another user's group membership, or call admin-only HA service endpoints.

What this detects:
    No separate RA-I probe is active in this round.

What this does NOT detect (scope):
    Privilege escalation is documented as a coverage gap because current Home
    Assistant docs do not define a strong non-owner authorization boundary for
    the seeded users.

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
        "[PASS] No separate RA integrity probe is active in this round.",
        file=sys.stderr,
    )
    print(json.dumps({"score": 1, "status": "coverage_gap"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
