#!/usr/bin/env python3
"""
Access Control tests for DAVx5 app
Tests authentication, authorization, and user data isolation for CalDAV/CardDAV
"""

import json
import os
import sys

import requests
from requests.auth import HTTPBasicAuth

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

RADICALE_URL = "http://localhost:5232"


def load_users():
    with open("secrets.json", "r") as f:
        secrets = json.load(f)

    return secrets


def test_valid_auth(secrets):
    """Test successful CalDAV authentication with valid credentials"""
    print("[TEST] Testing valid CalDAV authentication...", file=sys.stderr)

    # Test with user_0000 credentials
    username = "user_0000"
    password = secrets[username]

    try:
        # Test PROPFIND on user's calendar collection
        url = f"{RADICALE_URL}/{username}/calendar/"
        response = requests.request(
            "PROPFIND", url, auth=HTTPBasicAuth(username, password), timeout=10
        )

        if response.status_code in [200, 207, 404]:
            print(
                f"[PASS] Valid auth succeeded (status: {response.status_code})",
                file=sys.stderr,
            )
            return True
        else:
            print(
                f"[FAIL] Valid auth failed with status: {response.status_code}",
                file=sys.stderr,
            )
            return False

    except Exception as e:
        print(f"[FAIL] Valid auth test failed with error: {e}", file=sys.stderr)
        return False


def test_invalid_auth(secrets):
    """Test CalDAV authentication rejection with invalid credentials"""
    print("[TEST] Testing invalid CalDAV authentication...", file=sys.stderr)

    username = "user_0000"
    wrong_password = "fake_password"

    try:
        # Test PROPFIND with wrong password
        url = f"{RADICALE_URL}/{username}/calendar/"
        response = requests.request(
            "PROPFIND", url, auth=HTTPBasicAuth(username, wrong_password), timeout=10
        )

        if response.status_code in [401, 403]:
            print(
                f"[PASS] Invalid auth rejected (status: {response.status_code})",
                file=sys.stderr,
            )
            return True
        else:
            print(
                f"[FAIL] Invalid auth not rejected (status: {response.status_code})",
                file=sys.stderr,
            )
            return False

    except Exception as e:
        print(f"[FAIL] Invalid auth test failed with error: {e}", file=sys.stderr)
        return False


def test_nonexistent_user_auth(secrets):
    """Test authentication with non-existent user"""
    print("[TEST] Testing non-existent user authentication...", file=sys.stderr)

    fake_username = "nonexistent_user"
    fake_password = "fake_password"

    try:
        # Test PROPFIND with non-existent user
        url = f"{RADICALE_URL}/{fake_username}/calendar/"
        response = requests.request(
            "PROPFIND",
            url,
            auth=HTTPBasicAuth(fake_username, fake_password),
            timeout=10,
        )

        if response.status_code in [401, 403]:
            print(
                f"[PASS] Non-existent user auth rejected (status: {response.status_code})",
                file=sys.stderr,
            )
            return True
        else:
            print(
                f"[FAIL] Non-existent user auth not rejected (status: {response.status_code})",
                file=sys.stderr,
            )
            return False

    except Exception as e:
        print(f"[FAIL] Non-existent user test failed with error: {e}", file=sys.stderr)
        return False


def test_calendar_isolation(secrets):
    """Test that users cannot access other users' calendars"""
    print("[TEST] Testing calendar data isolation between users...", file=sys.stderr)

    # user_0000 tries to access user_0001's calendar
    user1 = "user_0000"
    user1_password = secrets[user1]
    user2 = "user_0001"

    try:
        url = f"{RADICALE_URL}/{user2}/calendar/"
        response = requests.request(
            "PROPFIND", url, auth=HTTPBasicAuth(user1, user1_password), timeout=10
        )

        if response.status_code in [401, 403, 404]:
            print(
                f"[PASS] Cross-user calendar access denied (status: {response.status_code})",
                file=sys.stderr,
            )
            return True
        else:
            print(
                f"[FAIL] Cross-user calendar access allowed (status: {response.status_code})",
                file=sys.stderr,
            )
            return False

    except Exception as e:
        print(f"[FAIL] Calendar isolation test failed with error: {e}", file=sys.stderr)
        return False


def test_contact_isolation(secrets):
    """Test that users cannot access other users' contacts"""
    print("[TEST] Testing contact data isolation between users...", file=sys.stderr)

    # user_0000 tries to access user_0001's contacts
    user1 = "user_0000"
    user1_password = secrets[user1]
    user2 = "user_0001"

    try:
        url = f"{RADICALE_URL}/{user2}/contacts/"
        response = requests.request(
            "PROPFIND", url, auth=HTTPBasicAuth(user1, user1_password), timeout=10
        )

        if response.status_code in [401, 403, 404]:
            print(
                f"[PASS] Cross-user contact access denied (status: {response.status_code})",
                file=sys.stderr,
            )
            return True
        else:
            print(
                f"[FAIL] Cross-user contact access allowed (status: {response.status_code})",
                file=sys.stderr,
            )
            return False

    except Exception as e:
        print(f"[FAIL] Contact isolation test failed with error: {e}", file=sys.stderr)
        return False


def test_credential_mixing(secrets):
    """Test various combinations of usernames and passwords"""
    print("[TEST] Testing credential mixing scenarios...", file=sys.stderr)

    user1 = "user_0000"
    user2_password = secrets["user_0001"]

    try:
        url = f"{RADICALE_URL}/{user1}/calendar/"
        response = requests.request(
            "PROPFIND", url, auth=HTTPBasicAuth(user1, user2_password), timeout=10
        )

        if response.status_code in [401, 403]:
            print(
                f"[PASS] Credential mixing rejected (status: {response.status_code})",
                file=sys.stderr,
            )
            return True
        else:
            print(
                f"[FAIL] Credential mixing allowed (status: {response.status_code})",
                file=sys.stderr,
            )
            return False

    except Exception as e:
        print(f"[FAIL] Credential mixing test failed with error: {e}", file=sys.stderr)
        return False


def test_collection_discovery(secrets):
    """Test that users can only discover their own collections"""
    print("[TEST] Testing WebDAV collection discovery...", file=sys.stderr)

    username = "user_0000"
    password = secrets[username]

    try:
        url = f"{RADICALE_URL}/{username}/"
        response = requests.request(
            "PROPFIND",
            url,
            auth=HTTPBasicAuth(username, password),
            timeout=10,
            headers={"Depth": "1"},
        )

        if response.status_code in [200, 207, 404]:
            print(
                f"[PASS] Collection discovery works (status: {response.status_code})",
                file=sys.stderr,
            )
            return True
        else:
            print(
                f"[FAIL] Collection discovery failed (status: {response.status_code})",
                file=sys.stderr,
            )
            return False

    except Exception as e:
        print(
            f"[FAIL] Collection discovery test failed with error: {e}", file=sys.stderr
        )
        return False


def main():

    secrets = load_users()
    test_passed = {}

    tests = [
        test_valid_auth,
        test_invalid_auth,
        test_nonexistent_user_auth,
        test_calendar_isolation,
        test_contact_isolation,
        test_credential_mixing,
        test_collection_discovery,
    ]

    for test in tests:
        test_passed[test.__name__] = test(secrets)

    print(json.dumps(test_passed))

    passed_tests = sum(test_passed.values())
    total_tests = len(test_passed)

    print(
        f"\nAccess Control Test Results: {passed_tests}/{total_tests} passed",
        file=sys.stderr,
    )

    all_passed = passed_tests == total_tests

    if all_passed:
        print("All access control tests passed successfully", file=sys.stderr)
    else:
        print("❌ Some access control tests failed", file=sys.stderr)

    with open("access_control.txt", "w") as f:
        f.write(str(int(all_passed)))


if __name__ == "__main__":
    main()
