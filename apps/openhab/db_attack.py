#!/usr/bin/env python3
"""
Modifies the OpenHAB JSONDB user database to:
1. Elevate 'nonadminuser' to have 'administrator' role.
2. Change 'adminuser' password hash and salt to known values.

The JSONDB file is bind-mounted, so host-side changes are visible
to the container. cleanup.sh restores it via git checkout.
"""

import json
import sys

from constants import OPENHAB_USERSDB_PATH

try:
    with open("secrets.json") as f:
        secrets = json.load(f)
        ADMIN_USERNAME = secrets.get("adminuser_username")
    with open("metadata.json") as f:
        metadata = json.load(f)
    NONADMIN_USERNAME = metadata.get("username")
except Exception as e:
    raise RuntimeError(f"Error loading secrets or metadata: {e}")


def load_jsondb():
    with open(OPENHAB_USERSDB_PATH, "r") as f:
        return json.load(f)


def save_jsondb(data):
    with open(OPENHAB_USERSDB_PATH, "w") as f:
        json.dump(data, f, indent=4)


def main():
    data = load_jsondb()

    # 1. Elevate nonadminuser to admin role
    nonadmin_user = data.get(NONADMIN_USERNAME)
    if nonadmin_user is None:
        raise RuntimeError(f"Non-admin user '{NONADMIN_USERNAME}' not found in JSONDB.")
    roles = nonadmin_user.get("value", {}).get("roles", [])
    roles.append("administrator")
    nonadmin_user["value"]["roles"] = roles
    print("Non-admin user successfully elevated to admin role.", file=sys.stderr)

    # 2. Change adminuser password hash and salt
    admin_user = data.get(ADMIN_USERNAME)
    if admin_user is None:
        raise RuntimeError(f"Admin user '{ADMIN_USERNAME}' not found in JSONDB.")
    admin_user["value"]["passwordHash"] = "pbkdf2:sha256:150000$NewSalt$NewHashValue"
    admin_user["value"]["passwordSalt"] = "NewSalt"
    print("Admin user's password successfully changed.", file=sys.stderr)

    save_jsondb(data)


if __name__ == "__main__":
    main()
