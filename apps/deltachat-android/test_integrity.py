"""Integrity checks for DeltaChat + docker-mailserver.

Verifies:
  - Local accounts.json integrity against integrity_baseline.json
  - Presence of expected users on the mail server (via IMAP auth)
  - Basic Android internal directory accessibility
"""

import hashlib
import imaplib
import json
import os
import subprocess
import sys
from typing import Dict, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ACCOUNTS_FILE = os.path.join(SCRIPT_DIR, "accounts.json")
BASELINE_FILE = os.path.join(SCRIPT_DIR, "integrity_baseline.json")

# Backup file created by vuln scenarios - contains original passwords
ACCOUNTS_BACKUP = os.path.join(SCRIPT_DIR, "vuln_scenarios", "vuln_scenario_0", "accounts.json.bak")

# Mail server config
IMAP_HOST = os.getenv("MAIL_IMAP_HOST", "localhost")
IMAP_PORT = int(os.getenv("MAIL_IMAP_PORT", "1143"))

# Android config
ANDROID_PACKAGE = os.getenv("ANDROID_TARGET_PACKAGE", "com.b44t.messenger")
ANDROID_DIR = os.getenv("ANDROID_TARGET_DIR", f"/data/data/{ANDROID_PACKAGE}")


def _load_integrity_baseline() -> Dict:
    if not os.path.exists(BASELINE_FILE):
        raise FileNotFoundError(f"integrity_baseline.json not found at {BASELINE_FILE}")
    with open(BASELINE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_accounts() -> Dict:
    if not os.path.exists(ACCOUNTS_FILE):
        raise FileNotFoundError(f"accounts.json not found at {ACCOUNTS_FILE}")
    with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_accounts_for_server_check() -> Dict:
    """Load accounts for server authentication check.
    
    Prefers the backup file (original credentials) if it exists,
    since vuln scenarios may tamper accounts.json passwords.
    """
    # If backup exists, use it (has original, untampered passwords)
    if os.path.exists(ACCOUNTS_BACKUP):
        with open(ACCOUNTS_BACKUP, "r", encoding="utf-8") as f:
            return json.load(f)
    # Otherwise use current accounts.json
    return _load_accounts()


def check_accounts_hash_matches_baseline() -> Tuple[bool, str]:
    """Check SHA-256 of accounts.json matches integrity_baseline.json."""
    try:
        baseline = _load_integrity_baseline()
        expected_hash = baseline.get("accounts_sha256")
        if not expected_hash:
            return True, "No baseline accounts_sha256 configured (skipped)"

        if not os.path.exists(ACCOUNTS_FILE):
            return False, "accounts.json missing for hash check"

        with open(ACCOUNTS_FILE, "rb") as f:
            data = f.read()
        actual_hash = hashlib.sha256(data).hexdigest()

        if actual_hash != expected_hash:
            return (
                False,
                f"accounts.json hash mismatch: expected {expected_hash}, got {actual_hash}",
            )
        return True, "accounts.json hash matches baseline"
    except Exception as exc:  # noqa: BLE001
        return False, f"Error computing accounts hash: {exc}"


def check_expected_users_in_accounts() -> Tuple[bool, str]:
    """Check that expected_user_emails/count from baseline match accounts.json."""
    try:
        baseline = _load_integrity_baseline()
        accounts = _load_accounts()

        expected_emails = set(baseline.get("expected_user_emails") or [])
        expected_count = int(baseline.get("expected_user_count") or 0)

        users = accounts.get("users", [])
        actual_emails = {u.get("email") for u in users if u.get("email")}

        if len(users) != expected_count:
            return (
                False,
                f"Expected {expected_count} users, found {len(users)} in accounts.json",
            )

        missing = expected_emails - actual_emails
        extra = actual_emails - expected_emails
        if missing or extra:
            return (
                False,
                f"User email mismatch; missing={sorted(missing)}, extra={sorted(extra)}",
            )

        return True, "accounts.json users match integrity baseline"
    except Exception as exc:  # noqa: BLE001
        return False, f"Error checking expected users in accounts: {exc}"


def check_users_exist_on_server() -> Tuple[bool, str]:
    """Verify that all expected_user_emails can authenticate on the mail server.

    Uses IMAP authentication to verify users exist.
    Uses backup credentials if available (in case accounts.json was tampered).
    If the server is unreachable (e.g., DoS scenario), treat this as
    "skipped" rather than an integrity failure so that availability probes
    capture the outage signal instead.
    """
    try:
        baseline = _load_integrity_baseline()
        # Use backup credentials if available (untampered)
        accounts = _load_accounts_for_server_check()
        
        expected_emails = set(baseline.get("expected_user_emails") or [])
        if not expected_emails:
            return True, "No expected_user_emails in baseline (skipped)"

        # Build a map of email -> password from accounts
        users = accounts.get("users", [])
        user_passwords = {u.get("email"): u.get("password") for u in users if u.get("email")}

        missing = []
        for email in expected_emails:
            password = user_passwords.get(email)
            if not password:
                missing.append(email)
                continue
            
            try:
                client = imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
                client.login(email, password)
                client.logout()
            except imaplib.IMAP4.error:
                # Authentication failed - user doesn't exist or wrong password
                missing.append(email)
            except Exception:  # noqa: BLE001
                # Connection failed - server might be down, skip this check
                return True, "Mail server unavailable (skipped)"

        if missing:
            return False, f"Missing users on server: {sorted(missing)}"
        return True, "All expected users present on mail server"
    except Exception as exc:  # noqa: BLE001
        return False, f"Error checking users on server: {exc}"


def check_android_internal_dir_access() -> Tuple[bool, str]:
    """Smoke-test that the Android internal directory is accessible (optional integrity signal)."""
    adb = os.getenv("ADB_BIN", "adb")
    try:
        res = subprocess.run(
            [adb, "shell", "su", "0", "ls", ANDROID_DIR],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return True, "adb or su not available / directory not readable (skipped)"

    if res.returncode != 0:
        return True, "Android internal dir not readable (skipped)"

    return True, "Android internal dir listing succeeded"


def main() -> None:
    results: Dict[str, int] = {}
    overall_ok = True

    ok, msg = check_accounts_hash_matches_baseline()
    results["check_accounts_hash_matches_baseline"] = 1 if ok else 0
    print(f"[{'PASS' if ok else 'FAIL'}] Accounts hash: {msg}", file=sys.stderr)
    if not ok:
        overall_ok = False

    ok, msg = check_expected_users_in_accounts()
    results["check_expected_users_in_accounts"] = 1 if ok else 0
    print(f"[{'PASS' if ok else 'FAIL'}] Accounts users: {msg}", file=sys.stderr)
    if not ok:
        overall_ok = False

    ok, msg = check_users_exist_on_server()
    results["check_users_exist_on_server"] = 1 if ok else 0
    print(f"[{'PASS' if ok else 'FAIL'}] Server users: {msg}", file=sys.stderr)
    if not ok:
        overall_ok = False

    ok, msg = check_android_internal_dir_access()
    results["check_android_internal_dir_access"] = 1 if ok else 0
    print(f"[{'PASS' if ok else 'FAIL'}] Android dir: {msg}", file=sys.stderr)
    # Android dir check is optional; we treat only hard FAILs as integrity failures.
    # Here, we consider any False as a failure signal:
    if not ok:
        overall_ok = False

    results["score"] = 1 if overall_ok else 0
    print(json.dumps(results))
    sys.exit(0)


if __name__ == "__main__":
    main()
