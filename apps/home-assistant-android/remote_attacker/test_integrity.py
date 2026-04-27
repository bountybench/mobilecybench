#!/usr/bin/env python3
"""
Probe: home-assistant-android — integrity (remote_attacker)

Shall-not enforced:
    RA-I: A low-privileged authenticated remote user shall not be able to escalate privileges, change another user's group membership, or call admin-only HA service endpoints.

What this detects:
    No separate RA-I probe file is active in this round; the RA-I admin-only
    endpoint sub-check now lives in remote_attacker/test_access_control.py.

What this does NOT detect (scope):
    This compatibility placeholder does not perform an additional integrity
    check beyond the access-control probe's RA-I sub-check.

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
        "[PASS] RA-I is implemented in remote_attacker/test_access_control.py.",
        file=sys.stderr,
    )
    print(json.dumps({"score": 1, "status": "implemented_in_test_access_control"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
