#!/usr/bin/env python3

import json
import sys
import os

# Import the account setup module to get credentials
try:
    from setup_accounts import get_user_profiles
except ImportError:
    print("Error: Could not import setup_accounts module", file=sys.stderr)
    sys.exit(1)


def generate_secrets():
    secrets = {}

    # Add user profile information
    user_profiles = get_user_profiles()

    # Add user credentials
    for profile in user_profiles:
        # Add password with user-specific key
        password_key = f"{profile['name']}_password"
        secrets[password_key] = profile["password"]

        # Add user ID for reference
        id_key = f"{profile['name']}_id"
        secrets[id_key] = profile["id"]

        # Add user role information
        role_key = f"{profile['name']}_role"
        if profile["is_owner"]:
            secrets[role_key] = "owner"
        elif profile["is_admin"]:
            secrets[role_key] = "admin"
        else:
            secrets[role_key] = "user"

    return secrets


def main():
    print("Generating secrets.json...")

    try:
        secrets = generate_secrets()

        # Write secrets.json
        with open("secrets.json", "w") as f:
            json.dump(secrets, f, indent=2)

        print("✅ Successfully generated secrets.json")
        print(f"📄 Contains {len(secrets)} secret entries:")
        for key in sorted(secrets.keys()):
            print(f"   - {key}")

    except Exception as e:
        print(f"❌ Failed to generate secrets.json: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
