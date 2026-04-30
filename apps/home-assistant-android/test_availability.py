#!/usr/bin/env python3
"""Entrypoint for malicious_app availability probes.

Aggregates all check_* functions covering MA-A (notification delivery) plus
the RA-A liveness sub-checks that were duplicated at the top-level entrypoint
in the legacy probe layout. The remote_attacker entrypoint (`remote_attacker/
test_availability.py`) reuses the same check_* functions.
"""
from __future__ import annotations

import json
import sys

from checks.check_companion_process_alive import check_companion_process_alive
from checks.check_ha_core_responding import check_ha_core_responding
from checks.check_notification_delivery_succeeds import (
    check_notification_delivery_succeeds,
)
from checks.check_tls_proxy_responding import check_tls_proxy_responding


def main() -> int:
    checks = [
        check_ha_core_responding,
        check_tls_proxy_responding,
        check_companion_process_alive,
        check_notification_delivery_succeeds,
    ]
    results: dict[str, int] = {}
    overall_success = True
    for check in checks:
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
