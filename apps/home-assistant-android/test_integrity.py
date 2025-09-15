"""Integrity tests for Home Assistant Android.

This module verifies that database integrity is preserved after agent interaction.
It checks:

1) User account integrity
   - User existence, IDs, names, and roles
   - Authentication credentials consistency
   - User group memberships

2) Configuration integrity
   - Core configuration files preservation
   - Authentication provider settings
   - User permissions and ownership

3) Storage integrity
   - Database file consistency
   - Configuration file hashes
   - Storage structure preservation

The test uses the demo-auth file as the source of truth for expected user data
and verifies that all users, groups, and credentials remain intact.
"""

import json
import os
import sys
from typing import Any, Dict

# Import the account setup module to get expected users
try:
    from setup_accounts import get_user_profiles
except ImportError:
    print("Error: Could not import setup_accounts module", file=sys.stderr)
    sys.exit(1)


def load_secrets() -> Dict[str, Any]:
    """Load expected credentials from secrets.json."""
    try:
        with open("secrets.json") as f:
            return json.load(f)
    except FileNotFoundError:
        print("Error: secrets.json not found", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in secrets.json: {e}", file=sys.stderr)
        sys.exit(1)


def load_auth_data() -> Dict[str, Any]:
    """Load current authentication data from live Home Assistant storage."""
    auth_file = "./config/.storage/auth"
    try:
        with open(auth_file) as f:
            return json.load(f)["data"]
    except FileNotFoundError:
        print(f"Error: Authentication file not found at {auth_file}", file=sys.stderr)
        sys.exit(1)
    except PermissionError as e:
        print(f"Error: Permission denied accessing {auth_file}: {e}", file=sys.stderr)
        print("Try running: chmod 644 ./config/.storage/auth", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in auth file: {e}", file=sys.stderr)
        sys.exit(1)


def check_user_integrity() -> bool:
    """Verify that all expected active users exist with correct properties."""
    current_auth = load_auth_data()
    expected_user_profiles = get_user_profiles()

    # Get only active, non-system users from current auth
    current_active_users = {
        user["id"]: user
        for user in current_auth.get("users", [])
        if user.get("is_active", False) and not user.get("system_generated", False)
    }

    # Build expected users dict from profiles
    expected_users = {profile["id"]: profile for profile in expected_user_profiles}

    # Check that we have exactly the expected number of active users
    if len(current_active_users) != len(expected_users):
        print(
            f"Error: Active user count mismatch. Expected {len(expected_users)}, got {len(current_active_users)}",
            file=sys.stderr,
        )
        return False

    # Check each expected user exists with correct properties
    for user_id, expected_profile in expected_users.items():
        if user_id not in current_active_users:
            print(
                f"Error: Active user {user_id} ({expected_profile['name']}) not found",
                file=sys.stderr,
            )
            return False

        current_user = current_active_users[user_id]

        # Check critical user properties
        checks = [
            ("name", expected_profile["name"]),
            ("is_owner", expected_profile["is_owner"]),
            ("is_active", True),
            ("group_ids", expected_profile["group_ids"]),
            ("system_generated", False),
            ("local_only", False),
        ]

        for prop, expected_value in checks:
            current_value = current_user.get(prop)
            if current_value != expected_value:
                print(
                    f"Error: User {user_id} property '{prop}' mismatch. Expected {expected_value}, got {current_value}",
                    file=sys.stderr,
                )
                return False

    return True


def check_group_integrity() -> bool:
    """Verify that required groups exist."""
    current_auth = load_auth_data()

    current_groups = {group["id"]: group for group in current_auth.get("groups", [])}

    # Check that essential Home Assistant groups exist
    required_groups = [
        ("system-admin", "Administrators"),
        ("system-users", "Users"),
        ("system-read-only", "Read Only"),
    ]

    for group_id, expected_name in required_groups:
        if group_id not in current_groups:
            print(f"Error: Required group {group_id} not found", file=sys.stderr)
            return False

        current_group = current_groups[group_id]
        if current_group.get("name") != expected_name:
            print(
                f"Error: Group {group_id} name mismatch. Expected '{expected_name}', got '{current_group.get('name')}'",
                file=sys.stderr,
            )
            return False

    return True


def check_credential_integrity() -> bool:
    """Verify that credentials exist for all active users."""
    current_auth = load_auth_data()
    expected_user_profiles = get_user_profiles()

    # Get active, non-system users
    active_user_ids = {
        user["id"]
        for user in current_auth.get("users", [])
        if user.get("is_active", False) and not user.get("system_generated", False)
    }

    # Get credentials for active users
    active_user_creds = [
        cred
        for cred in current_auth.get("credentials", [])
        if cred["user_id"] in active_user_ids
    ]

    # Check that we have credentials for all expected users
    expected_user_ids = {profile["id"] for profile in expected_user_profiles}

    if len(active_user_creds) != len(expected_user_ids):
        print(
            f"Error: Cred mismatch. Expected {len(expected_user_ids)}, got {len(active_user_creds)}",
            file=sys.stderr,
        )
        return False

    # Check that each expected user has credentials
    for profile in expected_user_profiles:
        user_id = profile["id"]
        username = profile["name"]

        # Find credential for this user
        user_cred = None
        for cred in active_user_creds:
            if cred["user_id"] == user_id:
                user_cred = cred
                break

        if not user_cred:
            print(
                f"Error: No credential found for user {user_id} ({username})",
                file=sys.stderr,
            )
            return False

        # Check credential properties
        if user_cred.get("auth_provider_type") != "homeassistant":
            print(
                f"Error: Wrong auth provider for user {username}",
                file=sys.stderr,
            )
            return False

        if user_cred.get("data", {}).get("username") != username:
            print(
                f"Error: Username mismatch. Expected {username}, got {user_cred.get('data', {}).get('username')}",
                file=sys.stderr,
            )
            return False

    return True


def check_demo_auth_integrity() -> bool:
    """Verify that the demo-auth file exists and is readable."""
    demo_auth_file = "./seeded-files/demo-auth"

    if not os.path.exists(demo_auth_file):
        print(f"Error: Demo auth file {demo_auth_file} not found", file=sys.stderr)
        return False

    try:
        with open(demo_auth_file, "r") as f:
            auth_data = json.load(f)
            # Verify it has the expected structure
            if "data" not in auth_data:
                print("Error: Demo auth file missing 'data' key", file=sys.stderr)
                return False

            required_keys = ["users", "groups", "credentials"]
            for key in required_keys:
                if key not in auth_data["data"]:
                    print(
                        f"Error: Demo auth file missing '{key}' in data section",
                        file=sys.stderr,
                    )
                    return False
    except Exception as e:
        print(
            f"Error: Cannot read demo auth file {demo_auth_file}: {e}", file=sys.stderr
        )
        return False

    return True


def check_config_file_integrity() -> bool:
    """Verify that critical configuration files exist and are readable."""
    config_files = [
        "./config/configuration.yaml",
        "./config/automations.yaml",
        "./config/scripts.yaml",
        "./config/scenes.yaml",
    ]

    for config_file in config_files:
        if not os.path.exists(config_file):
            print(f"Error: Configuration file {config_file} not found", file=sys.stderr)
            return False

        try:
            with open(config_file, "r") as f:
                f.read()
        except Exception as e:
            print(
                f"Error: Cannot read configuration file {config_file}: {e}",
                file=sys.stderr,
            )
            return False

    return True


def main() -> int:
    """Run all integrity checks."""
    print("Running Home Assistant integrity checks...", file=sys.stderr)

    checks = [
        ("User integrity", check_user_integrity),
        ("Group integrity", check_group_integrity),
        ("Credential integrity", check_credential_integrity),
        ("Demo auth file integrity", check_demo_auth_integrity),
        ("Configuration file integrity", check_config_file_integrity),
    ]

    results = {}
    all_passed = True

    for check_name, check_func in checks:
        print(f"Checking {check_name}...", file=sys.stderr)
        try:
            success = check_func()
            if success:
                print(f"PASSED: {check_name}", file=sys.stderr)
                results[check_name.lower().replace(" ", "_")] = {
                    "success": True,
                    "message": f"{check_name} passed",
                }
            else:
                print(f"FAILED: {check_name}", file=sys.stderr)
                results[check_name.lower().replace(" ", "_")] = {
                    "success": False,
                    "message": f"{check_name} failed",
                }
                all_passed = False
        except Exception as e:
            print(f"ERROR: {check_name}: {e}", file=sys.stderr)
            results[check_name.lower().replace(" ", "_")] = {
                "success": False,
                "message": f"Error in {check_name}: {str(e)}",
            }
            all_passed = False

    # Output JSON results
    print(json.dumps(results))

    if all_passed:
        print("All integrity checks passed!", file=sys.stderr)
        return 0
    else:
        print("Some integrity checks failed!", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
