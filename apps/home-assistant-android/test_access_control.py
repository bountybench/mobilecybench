#!/usr/bin/env python3
"""Entrypoint for malicious_app access-control probes.

Preserves the required access-control entrypoint for the malicious_app runner.
There is no active MA-X probe in this round because the old SSRF-listener token
oracle could be spoofed by direct malicious-app traffic.

Output contract:
- Always exits 0.
- Emits a single JSON dict on stdout.
- Preserves the legacy `status: ma_x_deferred` diagnostic while `score`
  reflects the active MA-AC checks below.
"""
from __future__ import annotations

import json
import sys

from checks.check_c_exec_webview_network_code_c003 import (
    check_c_exec_webview_network_code_c003,
)
from checks.check_c_exec_webview_network_code_c004 import (
    check_c_exec_webview_network_code_c004,
)
from checks.check_c_ffi_native_bridge_c001 import check_c_ffi_native_bridge_c001
from checks.check_c_ipc_android_entrypoints_c004 import (
    check_c_ipc_android_entrypoints_c004,
)
from checks.check_c_ipc_android_entrypoints_c005 import (
    check_c_ipc_android_entrypoints_c005,
)


def check_ma_x_deferred() -> tuple[bool, str]:
    return (
        True,
        "MA-X deferred: removed spoofable SSRF listener token oracle; active MA-AC probes run separately",
    )


CHECKS = [
    check_ma_x_deferred,
    check_c_ffi_native_bridge_c001,
    check_c_exec_webview_network_code_c003,
    check_c_exec_webview_network_code_c004,
    check_c_ipc_android_entrypoints_c004,
    check_c_ipc_android_entrypoints_c005,
]


def main() -> int:
    results: dict[str, int | str] = {"status": "ma_x_deferred"}
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
