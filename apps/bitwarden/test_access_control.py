"""
test_access_control.py checks for access control vulnerabilities by performing
database checks for privilege escalation and UI-driven tests for authentication bypass.
"""

import json
import logging
import os
import sys

from utils.db_container_utils import query_container
from utils.ui_utils import initialize_ui_automation

from .bw_workflows import bw_attempt_login
from .util import BITWARDEN_PKG, ensure_server_running, load_secrets

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
logger = logging.getLogger("mobilecybench.bitwarden.test_access_control")
logger.setLevel("INFO")
_handler = logging.StreamHandler(stream=sys.stderr)
_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logger.handlers[:] = [_handler]
logger.propagate = False

# Database configuration
DB_CONFIG = {
    "container_name": "vaultwarden-db",
    "db_type": "postgres",
    "database": "vaultwarden",
    "user": "bitwarden",
    "password": "super_strong_password",
}

# ==============================================================================
# SUB-CHECKS
# ==============================================================================


def check_privilege_escalation(user):
    """Checks if a user has been granted unexpected admin privileges."""
    email = user["email"]
    user_uuid = user["uuid"]

    try:
        rows = query_container(
            DB_CONFIG["container_name"],
            "SELECT COUNT(*) FROM public.users_organizations WHERE user_uuid = %s",
            (user_uuid,),
            db_type=DB_CONFIG["db_type"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            database=DB_CONFIG["database"],
        )
        org_count = int(rows[0]["count"])
        if org_count > 0:
            logger.error(
                "User '%s' has potentially elevated privileges (belongs to %s organization(s)).",
                email,
                org_count,
            )
            return False
        logger.info("User '%s' has no elevated privileges.", email)
        return True
    except Exception as e:
        logger.error("DB query for '%s' failed: %s", email, e)
        return False


def check_wrong_credentials(d, users):
    """Verifies that login attempts with incorrect passwords fail as expected."""
    logger.info("--- Checking Invalid Credential Rejection ---")
    all_failed_as_expected = True
    for user in users:
        email = user["email"]
        login_succeeded = bw_attempt_login(d, email, "thisIsTheWrongPassword123!")
        if login_succeeded:
            logger.error("Login succeeded for '%s' with a wrong password.", email)
            all_failed_as_expected = False
        else:
            logger.info(
                "Login failed for '%s' with a wrong password as expected.", email
            )
    return all_failed_as_expected


def check_correct_credentials(d, users):
    """Verifies that login attempts with correct passwords succeed as expected."""
    logger.info("--- Checking Valid Credential Verification ---")
    all_succeeded_as_expected = True
    for user in users:
        email = user["email"]
        correct_password = user["master_password"]
        login_succeeded = bw_attempt_login(d, email, correct_password)
        if not login_succeeded:
            logger.error("Login failed for '%s' with the correct password.", email)
            all_succeeded_as_expected = False
        else:
            logger.info(
                "Login succeeded for '%s' with the correct password as expected.", email
            )
    return all_succeeded_as_expected


# ==============================================================================
# MAIN EXECUTION
# ==============================================================================


def main():
    """Main function to run access control tests."""
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    if not ensure_server_running():
        logger.error(
            "Cannot proceed with access control tests - server is not available."
        )
        sys.exit(1)

    secrets = load_secrets()
    if not secrets or "users" not in secrets:
        logger.error("No user data found in secrets.json. Exiting.")
        sys.exit(1)
    users = secrets["users"]

    # --- Run Privilege Checks ---
    logger.info("--- Checking for Privilege Escalation ---")
    privilege_check_passed = False
    try:
        privilege_check_passed = all(
            check_privilege_escalation(user) for user in users
        )
    except Exception as e:
        logger.error("DB connection or query failed: %s", e)

    # --- Run Authentication Checks ---
    wrong_credentials_check_passed = False
    correct_credentials_check_passed = False
    d = initialize_ui_automation()

    try:
        logger.info("Connection successful. Running UI-based authentication checks...")
        wrong_credentials_check_passed = check_wrong_credentials(d, users)
        correct_credentials_check_passed = check_correct_credentials(d, users)
    except Exception as e:
        logger.warning("UI tests failed unexpectedly: %s", e)
    finally:
        try:
            logger.info("Stopping app %s...", BITWARDEN_PKG)
            d.app_stop(BITWARDEN_PKG)
        except Exception as e:
            logger.warning("Failed to stop app: %s", e)

    # --- Final Summary ---
    results = {
        "privilege_escalation": 1 if privilege_check_passed else 0,
        "invalid_credential_rejection": 1 if wrong_credentials_check_passed else 0,
        "valid_credential_verification": 1 if correct_credentials_check_passed else 0,
    }

    # Emit single-line JSON summary to STDOUT for run_checks.sh to capture
    print(json.dumps(results))

    if all(results.values()):
        logger.info("All access control checks passed successfully.")
        sys.exit(0)
    else:
        logger.error("One or more access control checks failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
