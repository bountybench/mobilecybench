#!/usr/bin/env python3
"""Entrypoint for malicious_app access-control probes."""
from __future__ import annotations

import json
import sys

from checks.check_c_ipc_android_entrypoints_c002 import (
    check_c_ipc_android_entrypoints_c002,
)

CHECKS = [
    check_c_ipc_android_entrypoints_c002,
]


def main() -> int:
    results: dict[str, int] = {}
    overall_success = True
    for check in CHECKS:
        try:
            success, message = check()
        except Exception as exc:
            success, message = False, f"infra error: {exc!r}"
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
