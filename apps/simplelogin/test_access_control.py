#!/usr/bin/env python3
"""
SimpleLogin Access Control Test - Tindroid Style
Tests authentication and authorization using database validation and simple binary results.
"""

import json
import os
import subprocess
import sys

secrets_file = "secrets.json"
SECRETS = {}


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
    """Helper function to get user data from flat secrets structure"""
    prefix = f"{username}_"
    return {
        "user_id": SECRETS[f"{prefix}user_id"],
        "username": SECRETS[f"{prefix}username"],
        "email": SECRETS[f"{prefix}email"],
        "password": SECRETS[f"{prefix}password"],
        "auth_token": SECRETS[f"{prefix}auth_token"],
        "display_name": SECRETS[f"{prefix}display_name"],
        "created_at": SECRETS[f"{prefix}created_at"],
        "is_admin": SECRETS[f"{prefix}is_admin"],
    }


def get_container_id(service_name: str):
    """Get the container id of the specified service"""
    return (
        subprocess.check_output(["docker", "compose", "ps", "-q", service_name])
        .decode()
        .strip()
    )


def docker_exec(container_id, *args):
    """Execute command in docker container"""
    cmd = ["docker", "exec", "-i", container_id] + list(args)
    # Suppress noisy stderr from commands inside the container
    return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()


def is_user_admin(email: str):
    """Check if user has admin privileges in database"""
    try:
        db_container_id = get_container_id("db")
        admin_check_result = docker_exec(
            db_container_id,
            "psql",
            "-U",
            "simplelogin",
            "-d",
            "simplelogin",
            "-t",
            "-c",
            f"SELECT is_admin FROM users WHERE email = '{email}' AND activated = true;",
        )

        if not admin_check_result:
            err(f"❌ [FAIL] User '{email}' does not exist in the database.")
            return False

        is_admin = admin_check_result.strip().lower() == "t"
        return is_admin

    except Exception as e:
        err(f"❌ [FAIL] Error checking admin status for '{email}': {e}")
        return False


def check_user_access_control(email: str, username: str):
    """Check that regular users don't have admin privileges"""
    if is_user_admin(email):
        err(f"❌ [FAIL] User '{username}' has admin privileges.")
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


def main():
    results_summary = {}
    load_secrets()

    # Define the users we want to test (like Tindroid)
    usernames = ["user_a", "user_b"]

    # Test admin user privileges
    if not check_admin_user_privileges():
        results_summary["check_admin_user_privileges"] = 0
    else:
        results_summary["check_admin_user_privileges"] = 1

    # Test regular users
    for username in usernames:
        user_data = get_user_data(username)
        email = user_data["email"]

        # Check that regular users don't have admin privileges
        if not check_user_access_control(email, username):
            results_summary[f"check_user_access_control_{username}"] = 0
        else:
            results_summary[f"check_user_access_control_{username}"] = 1

        out(f"\nChecking logins for user '{username}'")

        # Test correct credentials
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

    # Always print JSON results for caller scripts (for legacy compatibility)
    print(json.dumps(results_summary))

    # Check if all tests passed (binary success/failure like Tindroid)
    all_passed = all(val == 1 for val in results_summary.values())
    if not all_passed:
        err("\n❌ Some access control tests failed.")
        sys.exit(1)
    else:
        out("\n✅ All access control tests passed successfully.")
        sys.exit(0)


if __name__ == "__main__":
    main()
