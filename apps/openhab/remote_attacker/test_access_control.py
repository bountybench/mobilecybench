"""OpenHAB remote-attacker access-control entrypoint."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable, Mapping, Tuple

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from probe_lib import probe_status_for  # noqa: E402

from remote_attacker.checks.check_deny_remote_admin_operation import (  # noqa: E402
    check_deny_remote_admin_operation,
)
from remote_attacker.checks.check_live_rest_auth_matrix import (  # noqa: E402
    check_live_rest_auth_matrix,
)

CheckResult = Tuple[bool, str] | Tuple[bool, str, Mapping[str, str]]
CheckFn = Callable[[], CheckResult]

CHECKS: list[CheckFn] = [
    check_deny_remote_admin_operation,
    check_live_rest_auth_matrix,
]


def main() -> int:
    """Run owned RA-AC checks and emit one JSON object."""
    results: dict[str, int | str] = {}
    overall_secure = True
    for fn in CHECKS:
        try:
            result = fn()
            success, message = result[0], result[1]
            extra_status = result[2] if len(result) > 2 else {}
        except Exception as exc:  # pragma: no cover - entrypoint guardrail.
            success = False
            message = f"infra error: {exc!r}"
            extra_status = {}
        prefix = "[PASS]" if success else "[FAIL]"
        print(f"{prefix} {fn.__name__}: {message}", file=sys.stderr)
        results[fn.__name__] = 1 if success else 0
        results[f"{fn.__name__}_status"] = probe_status_for(success, message)
        # Explicit check statuses override the fallback when they provide a
        # more precise status such as blocked_missing_hydration_manifest.
        results.update(extra_status)
        overall_secure = overall_secure and success
    print(json.dumps({"score": 1 if overall_secure else 0, **results}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
