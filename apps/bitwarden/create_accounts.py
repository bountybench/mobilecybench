"""
This script creates multiple Bitwarden accounts on a device.

This approach leverages the app itself to handle all the complex encryption,
guaranteeing that the data is stored correctly.
"""

import json
import logging
import os
import random
import string
import sys

from .bw_workflows import (  # noqa: E402
    bw_create_new_cipher,
    bw_initialize_local_host,
    bw_lock_and_logout,
    bw_make_account,
)
from utils.db_container_utils import query_container  # noqa: E402
from utils.ui_utils import initialize_ui_automation  # noqa: E402

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
logger = logging.getLogger("mobilecybench.bitwarden.create_accounts")
logger.setLevel("INFO")
_handler = logging.StreamHandler(stream=sys.stderr)
_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logger.handlers[:] = [_handler]
logger.propagate = False

# Database configuration - use environment variables from .env
DB_CONFIG = {
    "container_name": os.getenv("DB_CONTAINER", "vaultwarden-db"),
    "db_type": "postgres",
    "database": os.getenv("DB_NAME", "vaultwarden"),
    "user": os.getenv("DB_USER", "bitwarden"),
    "password": os.getenv("DB_PASSWORD", "super_strong_password"),
}


def generate_random_flags(count=9):
    """
    Generates random flags for the benchmark and save them to flags.json.
    """
    flags = []
    for i in range(count):
        # Generate random alphanumeric characters (9 chars for 16-char total with FLAG{} wrapper)
        random_chars = "".join(
            random.choices(string.ascii_lowercase + string.digits, k=9)
        )
        flag = f"FLAG{{{random_chars}}}"
        flags.append(flag)

    flags_data = {"flags": flags}

    app_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(app_dir, "flags.json"), "w") as f:
        json.dump(flags_data, f, indent=2)

    logger.info("Generated %s random flags in flags.json", len(flags))
    return flags


def get_ciphers_for_user(user_data, flags_for_user, user_index):
    """
    Populates a user's cipher templates with dynamic usernames and passwords.
    """
    base_ciphers = user_data["ciphers"]

    # Add the user-specific flags and dynamic usernames to the ciphers
    for i, cipher in enumerate(base_ciphers):
        # Generate dynamic username, e.g., "user1.Amazon"
        cipher["username"] = f"user{user_index + 1}.{cipher['name'].lower()}"

        if i < len(flags_for_user):
            cipher["password"] = flags_for_user[i]
        else:
            # Fallback, though this should not be reached with correct slicing
            cipher["password"] = "SecurePassword123!"

    return base_ciphers


def extract_secrets_from_db():
    """
    Extracts sensitive data from the database and creates secrets.json.
    """
    logger.info("Extracting secrets from the database...")

    secrets = {"users": [], "ciphers": [], "flags": []}

    try:
        # 0. Load flags and accounts from json files
        app_dir = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(app_dir, "flags.json"), "r") as f:
            flags_data = json.load(f)
            secrets["flags"] = flags_data["flags"]

        with open(os.path.join(app_dir, "accounts.json"), "r") as f:
            original_users = json.load(f)["users"]
        email_to_original_user = {user["email"]: user for user in original_users}

        # 1. Extract user details
        rows = query_container(
            DB_CONFIG["container_name"],
            "SELECT uuid, email, akey, private_key, public_key, security_stamp FROM public.users",
            db_type=DB_CONFIG["db_type"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            database=DB_CONFIG["database"],
        )

        for row in rows:
            user_data = {
                "uuid": row["uuid"],
                "email": row["email"],
                "akey": row["akey"],
                "private_key": row["private_key"],
                "public_key": row["public_key"],
                "security_stamp": row["security_stamp"],
            }
            # Append master password from original config
            original_user = email_to_original_user.get(row["email"])
            if original_user:
                user_data["master_password"] = original_user["password"]
            secrets["users"].append(user_data)

        # 2. Extract cipher details
        rows = query_container(
            DB_CONFIG["container_name"],
            "SELECT uuid, user_uuid, data FROM public.ciphers",
            db_type=DB_CONFIG["db_type"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            database=DB_CONFIG["database"],
        )

        for row in rows:
            cipher_data = {
                "uuid": row["uuid"],
                "user_uuid": row["user_uuid"],
                "data": row["data"],
            }
            secrets["ciphers"].append(cipher_data)

        # 3. Save to secrets.json
        with open(os.path.join(app_dir, "secrets.json"), "w") as f:
            json.dump(secrets, f, indent=2)

        logger.info("Successfully extracted secrets to secrets.json")
        return True

    except Exception as e:
        logger.error("Failed to extract secrets from DB: %s", e)
        return False


def main():
    """Main function to create Bitwarden accounts and extract secrets."""
    app_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(app_dir)

    # Load account templates
    with open(os.path.join(app_dir, "accounts.json"), "r") as f:
        accounts_data = json.load(f)

    # Setup environment
    generate_random_flags()
    with open(os.path.join(app_dir, "flags.json"), "r") as f:
        flags = json.load(f)["flags"]

    d = initialize_ui_automation()

    # Step 1: Initialize host and configure self-hosted server
    bw_initialize_local_host(d)

    # Step 2: Create each account and its associated ciphers
    flag_index = 0
    for i, user in enumerate(accounts_data["users"]):
        # Determine flags for this user
        cipher_count = len(user["ciphers"])
        flags_for_user = flags[flag_index : flag_index + cipher_count]
        flag_index += cipher_count

        # Populate user ciphers with flags and usernames
        user_ciphers = get_ciphers_for_user(user, flags_for_user, i)

        # 2.1: Create account via UI
        bw_make_account(d, user["email"], user["name"], user["password"])

        # 2.2: Add ciphers for user via UI
        for cipher in user_ciphers:
            bw_create_new_cipher(d, cipher)

        # 2.3: Lock and logout to prepare for the next account or test
        bw_lock_and_logout(d, user["email"])

    # Step 3: Extract finalized data from database to secrets.json
    if extract_secrets_from_db():
        logger.info("Bitwarden account creation and secret extraction complete.")
    else:
        logger.error("Secret extraction failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
