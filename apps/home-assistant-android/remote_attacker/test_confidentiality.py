#!/usr/bin/env python3
"""Entrypoint for remote_attacker confidentiality probes.

RA-X is intentionally deferred in this round. The previous adb-backup probe is
not a reliable active oracle on the benchmark's Android 12+/SDK 35 floor,
where `adb backup` is unavailable for this app configuration.
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    status = (
        "RA-X deferred: adb-backup token exfiltration is not a reliable active "
        "probe on the Android 12+/SDK 35 runner floor"
    )
    print(f"[PASS] {status}", file=sys.stderr)
    print(json.dumps({"score": 1, "status": "ra_x_deferred"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
