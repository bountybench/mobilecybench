#!/usr/bin/env python3
"""Entrypoint for remote_attacker integrity probes.

Aggregates RA-I checks that observe post-exploit HA state. The legacy
admin-only-endpoint sub-check still lives in remote_attacker/test_access_control.py
for access-cell continuity.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from checks.check_auth_provider_functional_diff import (  # noqa: E402
    check_auth_provider_functional_diff,
)
from checks.check_automations_list_unchanged import (  # noqa: E402
    check_automations_list_unchanged,
)
from checks.check_no_unauthorized_alarm_state_change import (  # noqa: E402
    check_no_unauthorized_alarm_state_change,
)
from checks.check_no_unauthorized_lock_state_change import (  # noqa: E402
    check_no_unauthorized_lock_state_change,
)


def main() -> int:
    checks = [
        check_no_unauthorized_lock_state_change,
        check_no_unauthorized_alarm_state_change,
        check_automations_list_unchanged,
        check_auth_provider_functional_diff,
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
