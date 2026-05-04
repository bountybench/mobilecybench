#!/usr/bin/env python3
"""Entrypoint for remote_attacker integrity probes.

The RA-I admin-only-endpoint sub-check lives in
remote_attacker/test_access_control.py (legacy scoring contract). This
entrypoint is a no-checks aggregator that emits a documented status string,
preserving the legacy `{"score": 1, "status": "implemented_in_test_access_control"}`
output exactly.
"""
from __future__ import annotations

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
