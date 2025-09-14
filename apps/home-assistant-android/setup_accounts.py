#!/usr/bin/env python3

import json
import sys
from typing import Dict, Any, List


# User profiles to create
USER_PROFILES = [
    {
        "id": "9b3aa218a2504ba787cdc97a7b022f40",
        "name": "testuser",
        "password": "testuser123",
        "is_owner": True,
        "is_admin": True,
        "group_ids": ["system-admin"],
    },
    {
        "id": "e818f6b4e79348ffb2c15544e607c8f3",
        "name": "adminuser",
        "password": "adminuser123",
        "is_owner": False,
        "is_admin": True,
        "group_ids": ["system-admin"],
    },
    {
        "id": "aa2a77c1b4c54f4c9cb50e2e989aff9e",
        "name": "nonadminuser",
        "password": "nonadminuser123",
        "is_owner": False,
        "is_admin": False,
        "group_ids": ["system-users"],
    },
]


def get_user_profiles() -> List[Dict[str, Any]]:
    return USER_PROFILES.copy()


def get_active_users() -> List[Dict[str, Any]]:
    try:
        with open("seeded-files/demo-auth") as f:
            auth_data = json.load(f)["data"]

        active_users = []
        for user in auth_data.get("users", []):
            # Only include active, non-system users
            if user.get("is_active", False) and not user.get("system_generated", False):
                active_users.append(user)

        return active_users
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        # Fallback to user profiles if seeded-files/demo-auth file doesn't exist or is invalid
        return [
            {
                "id": profile["id"],
                "name": profile["name"],
                "is_owner": profile["is_owner"],
                "is_active": True,
                "group_ids": profile["group_ids"],
                "system_generated": False,
                "local_only": False,
            }
            for profile in USER_PROFILES
        ]


def create_auth_structure():
    # Create users list - only add our test users, let Home Assistant create system users
    users = []

    # Add user profiles only
    for profile in USER_PROFILES:
        users.append(
            {
                "id": profile["id"],
                "group_ids": profile["group_ids"],
                "is_owner": profile["is_owner"],
                "is_active": True,
                "name": profile["name"],
                "system_generated": False,
                "local_only": False,
            }
        )

    # Create groups
    groups = [
        {"id": "system-admin", "name": "Administrators"},
        {"id": "system-users", "name": "Users"},
        {"id": "system-read-only", "name": "Read Only"},
    ]

    # Create credentials with fixed IDs to match existing auth file
    credential_mappings = {
        "9b3aa218a2504ba787cdc97a7b022f40": "e494b30a83f14a69b4e377b47fe225e0",  # testuser
        "e818f6b4e79348ffb2c15544e607c8f3": "5deabd1593a44053aab6f8e9001188bd",  # adminuser
        "aa2a77c1b4c54f4c9cb50e2e989aff9e": "70d6759542884b65b358d0977cc0069f",  # nonadminuser
    }

    credentials = []
    for profile in USER_PROFILES:
        credentials.append(
            {
                "id": credential_mappings[profile["id"]],
                "user_id": profile["id"],
                "auth_provider_type": "homeassistant",
                "auth_provider_id": None,
                "data": {"username": profile["name"]},
            }
        )

    # Complete auth structure
    auth_structure = {
        "version": 1,
        "minor_version": 1,
        "key": "auth",
        "data": {
            "users": users,
            "groups": groups,
            "credentials": credentials,
            "refresh_tokens": [],
        },
    }

    return auth_structure


def setup_accounts():
    print("Setting up Home Assistant user accounts...")

    auth_structure = create_auth_structure()

    # Write demo-auth file
    demo_auth_path = "seeded-files/demo-auth"
    try:
        with open(demo_auth_path, "w") as f:
            json.dump(auth_structure, f, indent=2)
        print(f"✅ Created {demo_auth_path} with user accounts")
    except Exception as e:
        print(f"❌ Failed to create {demo_auth_path}: {e}")
        return False

    return True


def main():
    if not setup_accounts():
        print("❌ Account setup failed")
        sys.exit(1)

    print("✅ Account setup completed successfully")


if __name__ == "__main__":
    main()
