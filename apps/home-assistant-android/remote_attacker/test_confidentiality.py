#!/usr/bin/env python3
"""Entrypoint for remote_attacker confidentiality probes.

Aggregates the RA-X adb-backup token-exfiltration check.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from checks.check_no_token_exfil_via_adb_backup import (  # noqa: E402
    check_no_token_exfil_via_adb_backup,
)


def main() -> int:
    checks = [check_no_token_exfil_via_adb_backup]
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
