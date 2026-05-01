"""Entrypoint for malicious_app access-control probes."""

from __future__ import annotations

import json
import sys

from checks.check_runtime_package_metadata_ma_ac import (
    check_runtime_package_metadata_ma_ac,
)
from checks.check_static_os_metadata import check_static_os_metadata

CHECKS = [
    check_static_os_metadata,
    check_runtime_package_metadata_ma_ac,
]


def main() -> int:
    results: dict[str, int] = {}
    overall_secure = True
    for fn in CHECKS:
        try:
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
