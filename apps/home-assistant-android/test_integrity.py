#!/usr/bin/env python3
"""Entrypoint for malicious_app integrity probes.

Aggregates the legacy MA-I auth-store-drift check. See the docstring of
`checks/check_legacy_auth_store_drift.py` for the documented coverage gap
explaining why this probe is intentionally weak in this round.
"""
from __future__ import annotations

import json
import sys

from checks.check_legacy_auth_store_drift import check_legacy_auth_store_drift


def main() -> int:
    checks = [check_legacy_auth_store_drift]
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
