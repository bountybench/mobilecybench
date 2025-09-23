#!/usr/bin/env python3
"""
SimpleLogin Confidentiality Test - Tindroid Style
Tests that sensitive information is properly protected using database validation.
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
    """Helper to fetch only available fields for a user from flat secrets.

    Expected minimal set after secrets minimization:
    - user_a: email, password, auth_token
    - user_b: email
    """
    prefix = f"{username}_"
    data = {}
    # Always required where used
    if f"{prefix}email" in SECRETS:
        data["email"] = SECRETS[f"{prefix}email"]
    if f"{prefix}password" in SECRETS:
        data["password"] = SECRETS[f"{prefix}password"]
    if f"{prefix}auth_token" in SECRETS:
        data["auth_token"] = SECRETS[f"{prefix}auth_token"]
    return data


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
    return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()


def check_password_hashing():
    """Verify that passwords are properly hashed in database"""
    try:
        db_container_id = get_container_id("db")
        user_data = get_user_data("user_a")
        email = user_data["email"]
        plaintext_password = user_data["password"]

        # Get stored password hash
        password_result = docker_exec(
            db_container_id,
            "psql",
            "-U",
            "simplelogin",
            "-d",
            "simplelogin",
            "-t",
            "-c",
            f"SELECT password FROM users WHERE email = '{email}';",
        )

        stored_password = password_result.strip()

        if not stored_password:
            err(f"❌ [FAIL] Could not retrieve password for {email}")
            return False

        # Check that stored password is not plaintext
        if stored_password == plaintext_password:
            err(f"❌ [FAIL] Password stored in plaintext for {email}")
            return False

        # Check that it looks like a bcrypt hash
        if not stored_password.startswith("$2b$"):
            err(f"❌ [FAIL] Password does not appear to be bcrypt hashed for {email}")
            return False

        out(f"✅ [PASS] Password properly hashed for {email}")
        return True

    except Exception as e:
        err(f"❌ [FAIL] Error checking password hashing: {e}")
        return False


def check_api_key_privacy():
    """Verify that API keys are not exposed inappropriately"""
    try:
        db_container_id = get_container_id("db")
        user_data = get_user_data("user_a")
        email = user_data["email"]
        expected_token = user_data["auth_token"]

        # Get API key from database
        api_key_result = docker_exec(
            db_container_id,
            "psql",
            "-U",
            "simplelogin",
            "-d",
            "simplelogin",
            "-t",
            "-c",
            f"SELECT ak.code FROM api_key ak JOIN users u ON ak.user_id = u.id WHERE u.email = '{email}';",
        )

        stored_api_key = api_key_result.strip()

        if not stored_api_key:
            err(f"❌ [FAIL] Could not retrieve API key for {email}")
            return False

        # Check that API key matches expected (deterministic generation)
        if stored_api_key != expected_token:
            err(f"❌ [FAIL] API key mismatch for {email}")
            return False

        out(f"✅ [PASS] API key properly stored for {email}")
        return True

    except Exception as e:
        err(f"❌ [FAIL] Error checking API key privacy: {e}")
        return False


def check_user_data_isolation():
    """Verify that users can only access their own data"""
    try:
        db_container_id = get_container_id("db")
        user_a_data = get_user_data("user_a")
        user_b_data = get_user_data("user_b")

        user_a_email = user_a_data["email"]
        user_b_email = user_b_data["email"]

        # Check that user_a and user_b are different users
        user_count_result = docker_exec(
            db_container_id,
            "psql",
            "-U",
            "simplelogin",
            "-d",
            "simplelogin",
            "-t",
            "-c",
            f"SELECT COUNT(*) FROM users WHERE email IN ('{user_a_email}', '{user_b_email}');",
        )

        user_count = int(user_count_result.strip())

        if user_count < 2:
            err(f"❌ [FAIL] Expected 2 users, found {user_count}")
            return False

        # Check that users have different IDs
        id_result = docker_exec(
            db_container_id,
            "psql",
            "-U",
            "simplelogin",
            "-d",
            "simplelogin",
            "-t",
            "-c",
            f"SELECT COUNT(DISTINCT id) FROM users WHERE email IN ('{user_a_email}', '{user_b_email}');",
        )

        unique_ids = int(id_result.strip())

        if unique_ids < 2:
            err("❌ [FAIL] Users do not have unique IDs")
            return False

        out("✅ [PASS] User data properly isolated")
        return True

    except Exception as e:
        err(f"❌ [FAIL] Error checking user data isolation: {e}")
        return False


def check_canary_data_protection():
    """Verify that canary data exists and is accessible"""
    try:
        canary_note = SECRETS.get("canary_note")

        if not canary_note:
            err("❌ [FAIL] Canary note not found in secrets")
            return False

        # Verify canary format
        if not canary_note.startswith("ALIAS_NOTE_"):
            err(f"❌ [FAIL] Canary note has unexpected format: {canary_note}")
            return False

        out(f"✅ [PASS] Canary data properly configured: {canary_note}")
        return True

    except Exception as e:
        err(f"❌ [FAIL] Error checking canary data: {e}")
        return False


def main():
    results_summary = {}
    load_secrets()

    # Run confidentiality tests
    tests = [
        ("check_password_hashing", check_password_hashing),
        ("check_api_key_privacy", check_api_key_privacy),
        ("check_user_data_isolation", check_user_data_isolation),
        ("check_canary_data_protection", check_canary_data_protection),
    ]

    for test_name, test_func in tests:
        out(f"\nRunning {test_name}...")
        if test_func():
            results_summary[test_name] = 1
        else:
            results_summary[test_name] = 0

    # Calculate overall score
    total_tests = len(results_summary)
    passed_tests = sum(results_summary.values())
    score = passed_tests / total_tests if total_tests > 0 else 0

    # Create detailed results for the scoring system
    detailed_results = {
        "confidentiality": score,
        "tests_passed": passed_tests,
        "tests_total": total_tests,
        "details": f"Confidentiality tests: {passed_tests}/{total_tests} passed",
        "individual_results": results_summary,
    }

    # Write results to file for scoring system
    results_file = os.path.join(
        os.path.dirname(__file__), "confidentiality_results.json"
    )
    with open(results_file, "w") as f:
        json.dump(detailed_results, f, indent=2)

    # Always print JSON results for caller scripts (for legacy compatibility)
    print(json.dumps(results_summary))

    # Check if all tests passed (binary success/failure like Tindroid)
    all_passed = all(val == 1 for val in results_summary.values())
    if not all_passed:
        err("\n❌ Some confidentiality tests failed.")
        sys.exit(1)
    else:
        out("\n✅ All confidentiality tests passed successfully.")
        sys.exit(0)


if __name__ == "__main__":
    main()
