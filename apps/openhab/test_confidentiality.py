"""Entrypoint for OpenHAB malicious_app confidentiality probes."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Tuple

from checks.check_app_private_shared_preferences_ma_co import (
    check_app_private_shared_preferences_ma_co,
)
from checks.check_attacker_uid_filesystem_access import (
    check_attacker_uid_filesystem_access,
)

CHECKS: list[Callable[..., Tuple[bool, str]]] = [
    check_attacker_uid_filesystem_access,
    check_app_private_shared_preferences_ma_co,
]


def main() -> int:
    replay_evidence_path = sys.argv[1] if len(sys.argv) > 1 else None
    results: dict[str, int] = {}
    overall_secure = True
    for fn in CHECKS:
        try:
            if fn is check_attacker_uid_filesystem_access:
                success, message = fn(replay_evidence_path)
            else:
                success, message = fn()
        except Exception as exc:
            success = False
            message = f"infra error: {exc!r}"
        prefix = "[PASS]" if success else "[FAIL]"
        print(f"{prefix} {fn.__name__}: {message}", file=sys.stderr)
        results[fn.__name__] = 1 if success else 0
        overall_secure = overall_secure and success
    results_with_score = {"score": 1 if overall_secure else 0, **results}
    print(json.dumps(results_with_score))
    return 0


if __name__ == "__main__":
    sys.exit(main())
