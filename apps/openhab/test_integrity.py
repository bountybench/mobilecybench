"""Stage 4d entrypoint for malicious_app integrity probes."""

from __future__ import annotations

import json
import sys

from checks.check_runtime_package_metadata_ma_in import (
    check_runtime_package_metadata_ma_in,
)

CHECKS = [check_runtime_package_metadata_ma_in]


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
