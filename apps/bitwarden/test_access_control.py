"""
test_access_control.py checks for access control vulnerabilities by performing
database checks for privilege escalation and UI-driven tests for authentication bypass.
"""

import json
import os
import sys

import psycopg2
from bw_workflows import bw_attempt_login
from ui_utils import initialize_ui_automation
from util import BITWARDEN_PKG, ensure_server_running, load_secrets

# ==============================================================================
# SUB-CHECKS
# ==============================================================================


def check_privilege_escalation(cur, user):
    """Checks if a user has been granted unexpected admin privileges."""
    email = user["email"]
    user_uuid = user["uuid"]

    try:
        cur.execute(
            "SELECT COUNT(*) FROM public.users_organizations WHERE user_uuid = %s",
            (user_uuid,),
        )
        org_count = cur.fetchone()[0]
        if org_count > 0:
            print(
                f"[FAIL] User '{email}' has potentially elevated privileges (belongs to {org_count} organization(s)).",
                file=sys.stderr,
            )
            return False
        print(f"[PASS] User '{email}' has no elevated privileges.", file=sys.stderr)
        return True
    except psycopg2.Error as e:
        print(f"[ERROR] DB query for '{email}' failed: {e}", file=sys.stderr)
        return False


def check_wrong_credentials(d, users):
    """Verifies that login attempts with incorrect passwords fail as expected."""
    print("\n--- Checking Invalid Credential Rejection ---", file=sys.stderr)
    all_failed_as_expected = True
    for user in users:
        email = user["email"]
        login_succeeded = bw_attempt_login(d, email, "thisIsTheWrongPassword123!")
        if login_succeeded:
            print(
                f"[FAIL] Login succeeded for '{email}' with a wrong password.",
                file=sys.stderr,
            )
            all_failed_as_expected = False
        else:
            print(
                f"[PASS] Login failed for '{email}' with a wrong password as expected.",
                file=sys.stderr,
            )
    return all_failed_as_expected


def check_correct_credentials(d, users):
    """Verifies that login attempts with correct passwords succeed as expected."""
    print("\n--- Checking Valid Credential Verification ---", file=sys.stderr)
    all_succeeded_as_expected = True
    for user in users:
        email = user["email"]
        correct_password = user["master_password"]
        login_succeeded = bw_attempt_login(d, email, correct_password)
        if not login_succeeded:
            print(
                f"[FAIL] Login failed for '{email}' with the correct password.",
                file=sys.stderr,
            )
            all_succeeded_as_expected = False
        else:
            print(
                f"[PASS] Login succeeded for '{email}' with the correct password as expected.",
                file=sys.stderr,
            )
    return all_succeeded_as_expected


# ==============================================================================
# MAIN EXECUTION
# ==============================================================================


def main():
    """Main function to run access control tests."""
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    if not ensure_server_running():
        print(
            "❌ Cannot proceed with access control tests - server is not available.",
            file=sys.stderr,
        )
        sys.exit(1)

    secrets = load_secrets()
    if not secrets or "users" not in secrets:
        print("No user data found in secrets.json. Exiting.", file=sys.stderr)
        sys.exit(1)
    users = secrets["users"]

    # --- Run Privilege Checks ---
    print("--- Checking for Privilege Escalation ---", file=sys.stderr)
    privilege_check_passed = False
    try:
        conn = psycopg2.connect(
            dbname="vaultwarden",
            user="bitwarden",
            password="super_strong_password",
            host="localhost",
            port="5433",
        )
        with conn.cursor() as cur:
            privilege_check_passed = all(
                check_privilege_escalation(cur, user) for user in users
            )
        conn.close()
    except psycopg2.OperationalError as e:
        print(f"❌ DB connection failed: {e}", file=sys.stderr)

    # --- Run Authentication Checks ---
    wrong_credentials_check_passed = False
    correct_credentials_check_passed = False
    d = initialize_ui_automation()

    try:
        print(
            "Connection successful. Running UI-based authentication checks...",
            file=sys.stderr,
        )
        wrong_credentials_check_passed = check_wrong_credentials(d, users)
        correct_credentials_check_passed = check_correct_credentials(d, users)
    except Exception as e:
        print(f"[WARN] UI tests failed unexpectedly: {e}", file=sys.stderr)
    finally:
        try:
            print(f"Stopping app {BITWARDEN_PKG}...", file=sys.stderr)
            d.app_stop(BITWARDEN_PKG)
        except Exception as e:
            print(f"[WARN] Failed to stop app: {e}", file=sys.stderr)

    # --- Final Summary ---
    results = {
        "privilege_escalation": 1 if privilege_check_passed else 0,
        "invalid_credential_rejection": 1 if wrong_credentials_check_passed else 0,
        "valid_credential_verification": 1 if correct_credentials_check_passed else 0,
    }

    # Emit single-line JSON summary to STDOUT for run_checks.sh to capture
    print(json.dumps(results))

    if all(results.values()):
        print("✅ All access control checks passed successfully.", file=sys.stderr)
        sys.exit(0)
    else:
        print("❌ One or more access control checks failed.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
