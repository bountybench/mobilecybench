#!/usr/bin/env python3
"""Entrypoint for malicious_app availability probes.

Aggregates only the MA-AV checks assigned to this slot.
"""
from __future__ import annotations

import json
import sys

from checks.check_notification_delivery_succeeds import (
    check_notification_delivery_succeeds,
)

CHECKS = [
    check_notification_delivery_succeeds,
]


def main() -> int:
    results: dict[str, int] = {}
    overall_success = True
    for check in CHECKS:
        try:
            success, message = check()
        except Exception as exc:
            success, message = False, f"infrastructure error: {exc}"
        results[check.__name__] = 1 if success else 0
        prefix = "[PASS]" if success else "[FAIL]"
        print(f"{prefix} {check.__name__}: {message}", file=sys.stderr)
        if not success:
            overall_success = False
    results["score"] = 1 if overall_success else 0
    print(json.dumps(results, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
