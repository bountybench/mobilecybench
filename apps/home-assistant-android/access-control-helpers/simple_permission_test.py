#!/usr/bin/env python3
import argparse

import requests


def test_rest_permissions(hostname, token, user_type):
    base_url = f"http://{hostname}:8123/api"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    print(f"\n=== Testing {user_type} permissions ===")
    tests = [
        ("POST", "/states/sensor.test", "Create state", {"state": "test"}),
        ("DELETE", "/states/sensor.test", "Delete state"),
        ("GET", "/error_log", "View error log"),
    ]

    results = []
    for method, endpoint, description, *data in tests:
        try:
            if method == "GET":
                r = requests.get(f"{base_url}{endpoint}", headers=headers, timeout=5)
            elif method == "DELETE":
                r = requests.delete(f"{base_url}{endpoint}", headers=headers, timeout=5)
            else:
                payload = data[0] if data else {}
                r = requests.post(
                    f"{base_url}{endpoint}", headers=headers, json=payload, timeout=5
                )

            status = "✅ ALLOWED" if r.status_code < 400 else "❌ DENIED"
            details = f"({r.status_code})"

            results.append(
                {
                    "endpoint": endpoint,
                    "allowed": r.status_code < 400,
                    "status_code": r.status_code,
                    "description": description,
                }
            )

            print(f"{status:12} {method} {endpoint:20} - {description} {details}")

        except Exception as e:
            results.append(
                {
                    "endpoint": endpoint,
                    "allowed": False,
                    "status_code": None,
                    "description": description,
                    "error": str(e),
                }
            )
            print(f"{'❌ ERROR':12} {method} {endpoint:20} - {description} ({e})")

    return results


def run_permission_test(hostname: str, admin_token: str, user_token: str) -> dict:
    """
    Run permission tests with admin and user tokens.

    Args:
        hostname: Host address where HA is running
        admin_token: Admin Long-Lived Access Token
        user_token: User Long-Lived Access Token

    Returns:
        Dictionary containing test results with admin_results, user_results, and summary
    """
    print(f"Testing permissions on {hostname}:8123")
    print(f"Admin token: {admin_token[:20]}...")
    print(f"User token: {user_token[:20]}...")

    admin_results = test_rest_permissions(hostname, admin_token, "ADMIN")
    user_results = test_rest_permissions(hostname, user_token, "USER")

    admin_allow, user_allow = 0, 0
    for i, admin in enumerate(admin_results):
        user = user_results[i] if i < len(user_results) else {"allowed": False}
        if admin["allowed"]:
            admin_allow += 1
        if user["allowed"]:
            user_allow += 1

    print("\n=== Permission Summary ===")
    print(f"Admin allowed: {admin_allow}")
    print(f"User allowed: {user_allow}")

    return {
        "admin_results": admin_results,
        "user_results": user_results,
        "admin_allowed_count": admin_allow,
        "user_allowed_count": user_allow,
        "total_tests": len(admin_results),
    }


def main():
    parser = argparse.ArgumentParser(description="Test HA permissions with LLAT")
    parser.add_argument("--hostname", default="localhost", help="HA hostname")
    parser.add_argument("--admin-token", required=True, help="Admin LLAT")
    parser.add_argument("--user-token", required=True, help="User LLAT")

    args = parser.parse_args()

    # Use the refactored function
    results = run_permission_test(args.hostname, args.admin_token, args.user_token)

    # The function already prints the results, but we could return the data here
    # for further processing if needed
    return results


if __name__ == "__main__":
    main()
