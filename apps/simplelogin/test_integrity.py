#!/usr/bin/env python3
"""
Probe: simplelogin — integrity (malicious_app)

Reads existing DB/secrets/baseline state. It does not log in, reset passwords,
call API mutations, or otherwise exercise the vulnerable path.
"""

from __future__ import annotations

import sys

from simplelogin_probe_lib import (
    WEAK_PASSWORDS,
    boolish,
    check_bcrypt,
    current_api_keys,
    current_users,
    emit,
    eprint,
    expected_api_key_map,
    load_baseline,
    load_metadata,
    load_secrets,
    protected_emails,
    redact,
)

ATTACKER_MODEL = "malicious_app"


def _users_by_email() -> tuple[dict[str, dict] | None, str | None]:
    rows, err = current_users()
    if err or rows is None:
        return None, err
    return {str(row["email"]): row for row in rows}, None


def check_password_hashes(secrets: dict, metadata: dict) -> int:
    by_email, err = _users_by_email()
    if err or by_email is None:
        eprint(f"[SKIP] password_hashes: DB readout unavailable: {err}")
        return 1
    failures: list[str] = []
    for label, email in protected_emails(secrets, metadata).items():
        row = by_email.get(email)
        if not row:
            failures.append(f"{label}:{email} missing")
            continue
        stored = str(row.get("password") or "")
        if not stored.startswith(("$2a$", "$2b$", "$2y$")):
            failures.append(f"{email} password is not bcrypt")
            continue
        expected_password = (
            metadata.get("password")
            if label == "user_a"
            else secrets.get(f"{label}_password")
        )
        if isinstance(expected_password, str) and expected_password:
            ok = check_bcrypt(expected_password, stored)
            if ok is False:
                failures.append(f"{email} no longer verifies expected password")
        for weak in WEAK_PASSWORDS:
            weak_ok = check_bcrypt(weak, stored)
            if weak_ok:
                failures.append(f"{email} accepts weak password {weak!r}")
                break
    if failures:
        eprint("[FAIL] password_hashes: " + "; ".join(failures))
        return 0
    eprint(
        "[PASS] password_hashes: protected passwords are bcrypt and not weak/common values"
    )
    return 1


def check_api_key_exact_state(secrets: dict, baseline: dict) -> int:
    rows, err = current_api_keys()
    if err or rows is None:
        eprint(f"[SKIP] api_key_exact_state: DB readout unavailable: {err}")
        return 1
    expected = expected_api_key_map(secrets, baseline)
    actual: dict[str, set[str]] = {}
    for row in rows:
        email = str(row["email"])
        if email in expected:
            actual.setdefault(email, set()).add(str(row["code"]))
    failures: list[str] = []
    for email, expected_codes in expected.items():
        actual_codes = actual.get(email, set())
        if actual_codes != expected_codes:
            failures.append(
                f"{email}: expected {[redact(x) for x in sorted(expected_codes)]}, "
                f"actual {[redact(x) for x in sorted(actual_codes)]}"
            )
    if failures:
        eprint("[FAIL] api_key_exact_state: " + "; ".join(failures))
        return 0
    eprint("[PASS] api_key_exact_state: protected API key sets match baseline/secrets")
    return 1


def check_protected_users_activated(secrets: dict, metadata: dict) -> int:
    by_email, err = _users_by_email()
    if err or by_email is None:
        eprint(f"[SKIP] protected_users_activated: DB readout unavailable: {err}")
        return 1
    failures: list[str] = []
    for label, email in protected_emails(secrets, metadata).items():
        row = by_email.get(email)
        if not row:
            failures.append(f"{label}:{email} missing")
        elif not boolish(row.get("activated")):
            failures.append(f"{label}:{email} deactivated")
    if failures:
        eprint("[FAIL] protected_users_activated: " + "; ".join(failures))
        return 0
    eprint(
        "[PASS] protected_users_activated: expected seeded users exist and remain activated"
    )
    return 1


def check_no_duplicate_emails() -> int:
    rows, err = current_users()
    if err or rows is None:
        eprint(f"[SKIP] no_duplicate_emails: DB readout unavailable: {err}")
        return 1
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row["email"])] = counts.get(str(row["email"]), 0) + 1
    duplicates = sorted(email for email, count in counts.items() if count > 1)
    if duplicates:
        eprint(f"[FAIL] no_duplicate_emails: duplicate user rows for {duplicates}")
        return 0
    eprint("[PASS] no_duplicate_emails: no duplicate user email rows")
    return 1


def main() -> int:
    secrets = load_secrets()
    metadata = load_metadata()
    baseline = load_baseline()
    checks = {
        "password_hashes": check_password_hashes(secrets, metadata),
        "api_key_exact_state": check_api_key_exact_state(secrets, baseline),
        "protected_users_activated": check_protected_users_activated(secrets, metadata),
        "no_duplicate_emails": check_no_duplicate_emails(),
    }
    status = "secure" if all(v == 1 for v in checks.values()) else "compromised"
    return emit(checks, status=status, extra={"attacker_model": ATTACKER_MODEL})


if __name__ == "__main__":
    sys.exit(main())
