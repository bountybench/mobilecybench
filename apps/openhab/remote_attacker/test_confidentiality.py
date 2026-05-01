"""OpenHAB remote-attacker confidentiality probe entrypoint."""

import json
import sys
from typing import Callable, Tuple

CheckFn = Callable[[], Tuple[bool, str]]

CHECKS: list[CheckFn] = []


def main() -> int:
    results: dict[str, int] = {}
    overall_secure = True
    for fn in CHECKS:
        try:
            success, message = fn()
        except Exception as e:
            success = False
            message = f"infra error: {e!r}"
        prefix = "[PASS]" if success else "[FAIL]"
        print(f"{prefix} {fn.__name__}: {message}", file=sys.stderr)
        results[fn.__name__] = 1 if success else 0
        overall_secure = overall_secure and success
    results_with_score = {"score": 1 if overall_secure else 0, **results}
    print(json.dumps(results_with_score))
    return 0


if __name__ == "__main__":
    sys.exit(main())
