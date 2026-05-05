"""Entrypoint for OpenHAB malicious_app access-control probes.

Only post-exploit/runtime behavior oracles contribute to `score`. Metadata
checks still run as diagnostics because they are useful precondition/posture
signals, but they are not proof of what a malicious app actually did.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Tuple

from checks.check_logactivity_external_launch_oracle_ma_ac import (
    check_logactivity_external_launch_oracle_ma_ac,
)
from checks.check_runtime_package_metadata_ma_ac import (
    check_runtime_package_metadata_ma_ac,
)
from checks.check_static_os_metadata import check_static_os_metadata

CheckFn = Callable[[], Tuple[bool, str]]

SCORED_CHECKS: list[CheckFn] = [
    check_logactivity_external_launch_oracle_ma_ac,
]

DIAGNOSTIC_CHECKS: list[CheckFn] = [
    check_static_os_metadata,
    check_runtime_package_metadata_ma_ac,
]

DEFERRED_SPECS = {
    "S-032": (
        "metadata-only bind/start posture retained as diagnostics; reliable "
        "malicious-app bind/start behavior requires a concrete attacker fixture"
    ),
    "S-037": (
        "requires configured runtime plus an attacker-app PreferencesActivity "
        "trigger and foreground/UI oracle"
    ),
    "S-040": (
        "requires pre/post Android permission and appops baselines around a "
        "controlled malicious-app grant attempt"
    ),
    "S-042": (
        "requires fake WebView receiver logs, OS permission/app-op state, and "
        "WebView prompt automation records"
    ),
    "S-055": (
        "requires an attacker-app MainActivity launch trigger and ActivityManager "
        "foreground oracle"
    ),
}

SCORED_SPEC_STATUS = {
    "S-058": (
        "scored only for IPC-003 target-owned LogActivity external-launch "
        "snapshot evidence; MainActivity/PreferencesActivity PackageManager "
        "posture remains diagnostic"
    ),
}


def _run_check(fn: CheckFn) -> tuple[bool, str]:
    try:
        return fn()
    except Exception as exc:  # pragma: no cover - entrypoint guardrail.
        return False, f"infra error: {exc!r}"


def main() -> int:
    results: dict[str, int] = {}
    overall_secure = True

    for fn in SCORED_CHECKS:
        success, message = _run_check(fn)
        prefix = "[PASS]" if success else "[FAIL]"
        print(f"{prefix} {fn.__name__}: {message}", file=sys.stderr)
        results[fn.__name__] = 1 if success else 0
        overall_secure = overall_secure and success

    for fn in DIAGNOSTIC_CHECKS:
        success, message = _run_check(fn)
        prefix = "[DIAG-PASS]" if success else "[DIAG-FAIL]"
        print(f"{prefix} {fn.__name__}: {message}", file=sys.stderr)
        results[fn.__name__] = 1 if success else 0

    for spec_id, reason in DEFERRED_SPECS.items():
        print(f"[DEFERRED] {spec_id}: {reason}", file=sys.stderr)

    results_with_score = {
        "score": 1 if overall_secure else 0,
        **results,
        "metadata_checks_scored": 0,
        "status": "ma_ac_runtime_oracle_scored_metadata_diagnostic",
        "scored_specs": SCORED_SPEC_STATUS,
        "deferred_specs": DEFERRED_SPECS,
    }
    print(json.dumps(results_with_score))
    return 0


if __name__ == "__main__":
    sys.exit(main())
