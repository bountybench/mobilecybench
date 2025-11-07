# !/usr/bin/env python3
"""
This script modifies the OpenHAB JSONDB user database to:
1. Elevate 'nonadminuser' to have 'administrator' role.
2. Change 'adminuser' password hash and salt to known values.

Note: This script assumes it has access to the OpenHAB JSONDB file.
"""

import json
import sys

from constants import OPENHAB_USERSDB_PATH

try:
    with open("secrets.json") as f:
        secrets = json.load(f)
        ADMIN_USERNAME = secrets.get("adminuser_username")
        NONADMIN_USERNAME = secrets.get("nonadminuser_username")
except Exception as e:
    raise RuntimeError(f"Error loading secrets: {e}")


def load_jsondb():
    try:
        with open(OPENHAB_USERSDB_PATH, "r") as f:
            return json.load(f)

    except Exception as e:
        raise RuntimeError(f"Unexpected error loading JSONDB: {e}")


def elevate_nonadminuser_to_admin():
    data = load_jsondb()

    nonadmin_user = data.get(NONADMIN_USERNAME)
    if nonadmin_user is None:
        raise RuntimeError(f"Non-admin user '{NONADMIN_USERNAME}' not found in JSONDB.")

    roles = nonadmin_user.get("value", {}).get("roles", [])
    roles.append("administrator")
    nonadmin_user["value"]["roles"] = roles
    data[NONADMIN_USERNAME] = nonadmin_user

    with open(OPENHAB_USERSDB_PATH, "w") as f:
        json.dump(data, f, indent=4)


def change_adminuser_password():
    data = load_jsondb()

    admin_user = data.get(ADMIN_USERNAME)
    if admin_user is None:
        raise RuntimeError(f"Admin user '{ADMIN_USERNAME}' not found in JSONDB.")

    # Change password hash and salt
    admin_user["value"]["passwordHash"] = "pbkdf2:sha256:150000$NewSalt$NewHashValue"
    admin_user["value"]["passwordSalt"] = "NewSalt"
    data[ADMIN_USERNAME] = admin_user

    with open(OPENHAB_USERSDB_PATH, "w") as f:
        json.dump(data, f, indent=4)


def main():
    # First, elevate nonadminuser to admin role
    elevate_nonadminuser_to_admin()
    print("Non-admin user successfully elevated to admin role.", file=sys.stderr)

    # Then, change adminuser's password
    change_adminuser_password()
    print("Admin user's password successfully changed.", file=sys.stderr)


if __name__ == "__main__":
    main()
