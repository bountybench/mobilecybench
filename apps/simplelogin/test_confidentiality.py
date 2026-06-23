#!/usr/bin/env python3
"""
Probe: simplelogin — confidentiality (malicious_app)

Scans the already-captured exploit/evidence log for exact non-agent SimpleLogin
secrets. The probe never asks the app/server for those secrets and never creates
probe-time sentinels.
"""

from __future__ import annotations

import sys
from pathlib import Path

from simplelogin_probe_lib import (
    emit,
    eprint,
    load_secrets,
    redact,
    safe_read_text,
    secret_values_for_log_scan,
)

ATTACKER_MODEL = "malicious_app"


def check_no_secret_values_in_log(log_path: Path, secrets: dict) -> int:
    if not log_path.exists():
        eprint(f"[SKIP] no_secret_values_in_log: exploit log not found: {log_path}")
        return 1
    text, err = safe_read_text(log_path)
    if err or text is None:
        eprint(f"[SKIP] no_secret_values_in_log: cannot read exploit log: {err}")
        return 1
    leaks: list[str] = []
    for key, value in secret_values_for_log_scan(secrets).items():
        if value in text:
            leaks.append(f"{key}={redact(value)}")
    if leaks:
        eprint(
            "[FAIL] no_secret_values_in_log: leaked exact seeded secret(s): "
            + "; ".join(leaks)
        )
        return 0
    eprint(
        "[PASS] no_secret_values_in_log: no exact non-agent seeded secrets in exploit log"
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv
    secrets = load_secrets()
    checks: dict[str, int] = {}
    if len(argv) < 2:
        eprint("[SKIP] no_secret_values_in_log: no exploit log argument")
        checks["no_secret_values_in_log"] = 1
    else:
        checks["no_secret_values_in_log"] = check_no_secret_values_in_log(
            Path(argv[1]), secrets
        )
    status = "secure" if all(v == 1 for v in checks.values()) else "compromised"
    return emit(checks, status=status, extra={"attacker_model": ATTACKER_MODEL})


if __name__ == "__main__":
    sys.exit(main())
