"""OpenHAB remote-attacker availability probe entrypoint."""

from __future__ import annotations

import json
import sys
from typing import Callable, Tuple

CheckFn = Callable[[], Tuple[bool, str]]

CHECKS: list[CheckFn] = []


def main() -> int:
    """Run owned RA-AV checks and emit one JSON object."""
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
