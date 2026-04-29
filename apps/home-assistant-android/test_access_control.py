#!/usr/bin/env python3
"""Entrypoint for malicious_app access-control probes.

Preserves the legacy MA-X JSON contract. The current check is an inactive
compatibility placeholder because the old SSRF-listener token oracle could be
spoofed by direct malicious-app traffic.

Output contract preserved from the legacy probe:
- Always exits 0.
- Emits a single JSON dict on stdout containing per-check_* keys (1=pass,
  0=fail) and an aggregated `score` (1 iff all checks pass).
- Human-readable [PASS]/[FAIL] lines go to stderr.
"""
from __future__ import annotations

import json
import sys

from checks.check_no_functional_tokens_in_ssrf_listener import (
    check_no_functional_tokens_in_ssrf_listener,
)


def main() -> int:
    checks = [check_no_functional_tokens_in_ssrf_listener]
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
