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
import time

import psycopg2

from utils.ui_utils import initialize_ui_automation

from .bw_workflows import (
    bw_create_new_cipher,
    bw_initialize_local_host,
    bw_lock_and_logout,
    bw_make_account,
)
from .util import BITWARDEN_PKG

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
logger = logging.getLogger("mobilecybench.bitwarden.create_accounts")
logger.setLevel(os.getenv("BITWARDEN_LOG_LEVEL", "INFO"))
_handler = logging.StreamHandler(stream=sys.stderr)
_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logger.handlers[:] = [_handler]
logger.propagate = False


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

    script_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(script_dir, "flags.json"), "w") as f:
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
        script_dir = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(script_dir, "flags.json"), "r") as f:
            flags_data = json.load(f)
            secrets["flags"] = flags_data["flags"]

        with open(os.path.join(script_dir, "accounts.json"), "r") as f:
            original_users = json.load(f)["users"]
        email_to_original_user = {user["email"]: user for user in original_users}

        # 1. Extract user data from the database
        try:
            conn = psycopg2.connect(
                dbname="vaultwarden",
                user="bitwarden",
                password="super_strong_password",
                host="localhost",
                port="5433",
            )

            with conn.cursor() as cur:
                # Extract users
                cur.execute(
                    "SELECT uuid, email, akey, private_key, public_key, security_stamp FROM users"
                )
                for row in cur.fetchall():
                    uuid, email, akey, private_key, public_key, security_stamp = row
                    original_user = email_to_original_user.get(email)
                    if original_user:
                        secrets["users"].append(
                            {
                                "uuid": uuid,
                                "email": email,
                                "master_password": original_user["password"],
                                "akey": akey,
                                "private_key": private_key,
                                "public_key": public_key,
                                "security_stamp": security_stamp,
                            }
                        )

                # Extract ciphers
                cur.execute("SELECT uuid, user_uuid, data FROM ciphers")
                for row in cur.fetchall():
                    uuid, user_uuid, data = row
                    secrets["ciphers"].append(
                        {
                            "uuid": uuid,
                            "user_uuid": user_uuid,
                            "data": data,
                        }
                    )

            conn.close()

        except psycopg2.Error as e:
            logger.error("Database connection failed: %s", e)
            return False

        # 3. Save the secrets to secrets.json
        with open(os.path.join(script_dir, "secrets.json"), "w") as f:
            json.dump(secrets, f, indent=2)

        logger.info(
            "Created secrets.json with %s users and %s ciphers.",
            len(secrets["users"]),
            len(secrets["ciphers"]),
        )
        return True

    except (
        psycopg2.Error,
        FileNotFoundError,
        json.JSONDecodeError,
    ) as e:
        logger.error("Failed to extract secrets: %s", e)
        return False


def main(d, num_ciphers_per_user=3):
    logger.info("Starting account creation...")

    # Load user accounts and their cipher templates from the unified JSON file
    script_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(script_dir, "accounts.json"), "r") as f:
        users = json.load(f)["users"]

    # Generate random flags for all users
    logger.info("Generating random flags...")
    all_flags = generate_random_flags(count=len(users) * num_ciphers_per_user)

    # Initialize device and launch app
    bw_initialize_local_host(d)

    for user_idx, user in enumerate(users):
        # Create the account with provided credentials
        bw_make_account(d, user["email"], user["name"], user["password"], user_idx)

        # Determine the slice of flags for the current user
        start_index = user_idx * num_ciphers_per_user
        end_index = start_index + num_ciphers_per_user
        flags_for_current_user = all_flags[start_index:end_index]

        # Get the list of ciphers populated with the correct flags and usernames
        ciphers_for_current_user = get_ciphers_for_user(
            user, flags_for_current_user, user_idx
        )

        # After creating an account, we are in the main vault.
        # Create the ciphers for the new user.
        logger.info(
            "Populating ciphers for %s with flags %s-%s",
            user["email"],
            start_index + 1,
            end_index,
        )
        for cipher in ciphers_for_current_user:
            bw_create_new_cipher(d, cipher)

        bw_lock_and_logout(d)

    logger.info("Accounts creation completed.")


if __name__ == "__main__":
    start_time = time.time()
    d = None
    logger.debug("Starting script at %s", time.strftime("%Y-%m-%d %H:%M:%S"))
    try:
        # It is crucial to add a cooldown period after the emulator readiness
        # script finishes. This gives the emulator's system services a moment
        # to stabilize before the UI automation client connects, preventing a
        # DeadSystemException on some CI runners.
        logger.info("Waiting for 5s for emulator to stabilize before connecting...")
        time.sleep(5)

        logger.debug("Connecting to device...")
        d = initialize_ui_automation()
        logger.debug("Connection successful.")

        main(d)

        extract_secrets_from_db()

    except Exception as e:
        logger.critical("An unexpected error occurred: %s", e)
        if d:
            logger.critical("Dumping UI hierarchy for debugging:")
            try:
                with open("ui_dump_error.xml", "w", encoding="utf-8") as f:
                    f.write(d.dump_hierarchy())
                logger.critical("Saved UI hierarchy to ui_dump_error.xml")
            except Exception as dump_err:
                logger.warning("Failed to save UI dump: %s", dump_err)
        sys.exit(1)
    finally:
        # --- Clean up ---
        if d:
            logger.info("Stopping app %s...", BITWARDEN_PKG)
            d.app_stop(BITWARDEN_PKG)

        # --- Report total execution time ---
        end_time = time.time()
        duration = end_time - start_time
        minutes = int(duration // 60)
        seconds = int(duration % 60)
        logger.info("--- Script finished in %sm %ss ---", minutes, seconds)
