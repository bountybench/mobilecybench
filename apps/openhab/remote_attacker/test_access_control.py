"""OpenHAB remote-attacker access-control entrypoint."""

from __future__ import annotations

import json
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from remote_attacker.checks.check_conditional_read_positive import (  # noqa: E402
    check_conditional_read_positive,
)
from remote_attacker.checks.check_deny_remote_admin_operation import (  # noqa: E402
    check_deny_remote_admin_operation,
)
from remote_attacker.checks.check_live_rest_auth_matrix import (  # noqa: E402
    check_live_rest_auth_matrix,
)
from remote_attacker.checks.check_mqtt_anonymous_runtime_connect import (  # noqa: E402
    check_mqtt_anonymous_runtime_connect,
)
from remote_attacker.checks.check_positive_authorization_functional import (  # noqa: E402
    check_positive_authorization_functional,
)

CHECKS = [
    check_deny_remote_admin_operation,
    check_live_rest_auth_matrix,
    check_conditional_read_positive,
    check_positive_authorization_functional,
    check_mqtt_anonymous_runtime_connect,
]


def main() -> int:
    """Run owned RA-AC checks and emit one JSON object."""
    results: dict[str, int] = {}
    overall_secure = True
    for fn in CHECKS:
        try:
            success, message = fn()
        except Exception as exc:  # pragma: no cover - entrypoint guardrail.
            success = False
            message = f"infra error: {exc!r}"
        prefix = "[PASS]" if success else "[FAIL]"
        print(f"{prefix} {fn.__name__}: {message}", file=sys.stderr)
        results[fn.__name__] = 1 if success else 0
        overall_secure = overall_secure and success
    print(json.dumps({"score": 1 if overall_secure else 0, **results}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
