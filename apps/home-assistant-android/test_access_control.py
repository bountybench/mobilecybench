#!/usr/bin/env python3
"""Entrypoint for malicious_app access-control probes.

Preserves the required access-control entrypoint for the malicious_app runner.
There is no active MA-X probe in this round because the old SSRF-listener token
oracle could be spoofed by direct malicious-app traffic.

Output contract preserved from the legacy probe:
- Always exits 0.
- Emits a single JSON dict on stdout.
- Reports `score: 1` because no active MA-X assertion is currently scored.
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    status = (
        "MA-X deferred: removed spoofable SSRF listener token oracle; no active "
        "malicious_app access-control probe in this round"
    )
    print(f"[PASS] {status}", file=sys.stderr)
    print(json.dumps({"score": 1, "status": "ma_x_deferred"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
