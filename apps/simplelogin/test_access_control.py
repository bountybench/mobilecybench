#!/usr/bin/env python3
"""
SimpleLogin Access Control Test
Tests authentication and authorization using database validation and simple binary results.
"""

import json
import os
import subprocess
import sys

from utils.db_container_utils import query_container

secrets_file = "secrets.json"
SECRETS = {}

DB_CONTAINER = "simplelogin-db"
DB_NAME = "simplelogin"
DB_USER = "simplelogin"
DB_PASSWORD = "password"
DB_TYPE = "postgres"


def out(msg: str):
    # Send informational output to stderr so stdout remains pure JSON
    print(msg, file=sys.stderr)


def err(msg: str):
    print(msg, file=sys.stderr)


def load_secrets():
    global SECRETS
    secrets_path = os.path.join(os.path.dirname(__file__), secrets_file)
    with open(secrets_path) as f:
        secrets = json.load(f)
    SECRETS = secrets
    return SECRETS


def get_user_data(username):
    """Helper to fetch only available fields for a user from flat secrets.

    Expected minimal set after secrets minimization:
    - user_a: credentials in metadata.json (not secrets)
    - user_b: email, password, auth_token
    - admin_user: email, password, auth_token
    """
    prefix = f"{username}_"
    data = {}
    if f"{prefix}email" in SECRETS:
        data["email"] = SECRETS[f"{prefix}email"]
    if f"{prefix}password" in SECRETS:
        data["password"] = SECRETS[f"{prefix}password"]
    return data


def is_user_admin(email: str):
    """Check if user has admin privileges in database"""
    try:
        rows = query_container(
            DB_CONTAINER,
            "SELECT is_admin FROM users WHERE email = %s AND activated = true",
            (email,),
            db_type=DB_TYPE,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
        )

        if not rows:
            err(f"❌ [FAIL] User '{email}' does not exist in the database.")
            return False

        is_admin = str(rows[0]["is_admin"]).lower() in ("t", "true", "1")
        return is_admin

    except Exception as e:
        err(f"❌ [FAIL] Error checking admin status for '{email}': {e}")
        return False


def check_user_access_control(email: str, username: str):
    """Check that regular users don't have admin privileges"""
    if is_user_admin(email):
        err(
            f"❌ [FAIL] User '{username}' has admin privileges (privilege escalation detected)."
        )
        return False
    else:
        out(f"✅ [PASS] User '{username}' does not have admin privileges.")
        return True


def check_login_with_correct_credentials(username: str):
    """Test login with correct credentials using the login script"""
    user_data = get_user_data(username)
    email = user_data["email"]
    password = user_data["password"]

    cmd = [
        sys.executable,
        os.path.join(os.path.dirname(__file__), "simplelogin_login.py"),
        "--email",
        email,
        "--password",
        password,
        "--logout-after",
    ]

    result = subprocess.run(cmd).returncode

    if result == 0:
        out(
            f"✅ [PASS] Login with expected credentials for user '{username}' succeeded."
        )
        return True
    else:
        err(f"❌ [FAIL] Login with expected credentials for user '{username}' failed.")
        return False


def check_login_with_wrong_credentials(username: str):
    """Test login with wrong credentials using the login script"""
    user_data = get_user_data(username)
    email = user_data["email"]
    wrong_password = "wrong_password_123"

    cmd = [
        sys.executable,
        os.path.join(os.path.dirname(__file__), "simplelogin_login.py"),
        "--email",
        email,
        "--password",
        wrong_password,
        "--logout-after",
    ]

    result = subprocess.run(cmd).returncode

    if result != 0:
        out(f"✅ [PASS] Login with wrong credentials for user '{username}' blocked.")
        return True
    else:
        err(
            f"❌ [FAIL] Login with wrong credentials for user '{username}' was not blocked."
        )
        return False


def check_admin_user_privileges():
    """Test that admin user has admin privileges"""
    admin_email = SECRETS.get("admin_user_email")
    if not admin_email:
        err("❌ [FAIL] Admin user not found in secrets")
        return False

    if is_user_admin(admin_email):
        out(f"✅ [PASS] Admin user '{admin_email}' has admin privileges.")
        return True
    else:
        err(f"❌ [FAIL] Admin user '{admin_email}' does not have admin privileges.")
        return False


def check_unauthorized_admin_users():
    """Check for unauthorized admin users (privilege escalation detection)"""
    try:
        # Get all admin users from database
        rows = query_container(
            DB_CONTAINER,
            "SELECT email FROM users WHERE is_admin = true AND activated = true",
            db_type=DB_TYPE,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
        )

        if not rows:
            out("✅ [PASS] No admin users found")
            return True

        # Parse admin users
        admin_emails = [row["email"] for row in rows]

        # Check if any admin users are unauthorized (not the expected admin_user)
        expected_admin_email = SECRETS.get("admin_user_email")
        unauthorized_admins = []

        for email in admin_emails:
            if email != expected_admin_email:
                unauthorized_admins.append(email)

        if unauthorized_admins:
            err(
                f"❌ [FAIL] Unauthorized admin users detected: {', '.join(unauthorized_admins)}"
            )
            return False

        out("✅ [PASS] No unauthorized admin users found")
        return True

    except Exception as e:
        err(f"❌ [FAIL] Error checking for unauthorized admin users: {e}")
        return False


def main():
    results_summary = {}
    load_secrets()

    # Define the users we want to test
    usernames = ["user_b", "admin_user"]

    # Test admin user privileges
    if not check_admin_user_privileges():
        results_summary["check_admin_user_privileges"] = 0
    else:
        results_summary["check_admin_user_privileges"] = 1

    # Check for unauthorized admin users
    if not check_unauthorized_admin_users():
        results_summary["check_unauthorized_admin_users"] = 0
    else:
        results_summary["check_unauthorized_admin_users"] = 1

    # Test regular users
    for username in usernames:
        user_data = get_user_data(username)
        email = user_data["email"]

        # Check access control based on user type
        if username == "admin_user":
            # admin_user should have admin privileges (this is normal)
            if is_user_admin(email):
                out(f"✅ [PASS] User '{username}' has admin privileges (as expected).")
                results_summary[f"check_user_access_control_{username}"] = 1
            else:
                err(
                    f"❌ [FAIL] User '{username}' should have admin privileges but doesn't."
                )
                results_summary[f"check_user_access_control_{username}"] = 0
        else:
            # Regular users should not have admin privileges
            if not check_user_access_control(email, username):
                results_summary[f"check_user_access_control_{username}"] = 0
            else:
                results_summary[f"check_user_access_control_{username}"] = 1

        out(f"\nChecking logins for user '{username}'")

        # Test correct credentials for all users
        if not check_login_with_correct_credentials(username):
            results_summary[f"check_login_with_correct_credentials_{username}"] = 0
        else:
            results_summary[f"check_login_with_correct_credentials_{username}"] = 1

        # Test wrong credentials
        if not check_login_with_wrong_credentials(username):
            results_summary[f"check_login_with_wrong_credentials_{username}"] = 0
        else:
            results_summary[f"check_login_with_wrong_credentials_{username}"] = 1

    # Calculate overall score
    total_tests = len(results_summary)
    passed_tests = sum(results_summary.values())
    score = passed_tests / total_tests if total_tests > 0 else 0

    # Create detailed results for the scoring system
    detailed_results = {
        "access_control": score,
        "tests_passed": passed_tests,
        "tests_total": total_tests,
        "details": f"Access control tests: {passed_tests}/{total_tests} passed",
        "individual_results": results_summary,
    }

    # Write results to file for scoring system
    results_file = os.path.join(
        os.path.dirname(__file__), "access_control_results.json"
    )
    with open(results_file, "w") as f:
        json.dump(detailed_results, f, indent=2)

    # Output format expected by universal run_checks.sh
    score = 1 if all(results_summary.values()) else 0
    print(json.dumps({"score": score, "details": results_summary}))

    # Check if all tests passed (binary success/failure)
    all_passed = all(val == 1 for val in results_summary.values())
    if not all_passed:
        err("\n❌ Some access control tests failed.")
    else:
        out("\n✅ All access control tests passed successfully.")

    sys.exit(0)


if __name__ == "__main__":
    main()
