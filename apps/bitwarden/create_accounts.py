"""
This script creates multiple Bitwarden accounts directly in the database.

This optimized approach bypasses UI automation by creating users and ciphers
directly in the Vaultwarden database for much faster setup.
"""

import json
import logging
import os
import random
import string
import sys
import time
import hashlib
import base64
import uuid

import psycopg2

from .util import BITWARDEN_PKG

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
logger = logging.getLogger("mobilecybench.bitwarden.create_accounts")
logger.setLevel("INFO")
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


def create_user_in_database(conn, email, name, password):
    """Create a user directly in the database."""
    logger.info(f"Creating user {email} in database...")

    user_uuid = str(uuid.uuid4())
    security_stamp = str(uuid.uuid4())

    # Generate simplified keys for testing
    akey = base64.b64encode(os.urandom(32)).decode('utf-8')
    private_key = base64.b64encode(os.urandom(256)).decode('utf-8')
    public_key = base64.b64encode(os.urandom(64)).decode('utf-8')

    # Create password hash
    salt = email.lower().encode('utf-8')
    password_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    password_hash_b64 = base64.b64encode(password_hash).decode('utf-8')

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO users (
                uuid, email, name, password_hash, akey, private_key,
                public_key, security_stamp, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
            )
        """, (user_uuid, email, name, password_hash_b64, akey, private_key, public_key, security_stamp))

    logger.info(f"Created user {email} with UUID {user_uuid}")
    return user_uuid


def create_cipher_in_database(conn, user_uuid, name, username, password, website):
    """Create a cipher directly in the database."""
    logger.info(f"Creating cipher {name} for user {user_uuid}")

    cipher_uuid = str(uuid.uuid4())

    cipher_data = {
        "type": 1,  # Login type
        "name": name,
        "login": {
            "username": username,
            "password": password,
            "uris": [{"uri": website}] if website else []
        }
    }

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO ciphers (
                uuid, user_uuid, organization_uuid, type, data,
                created_at, updated_at, revision_date
            ) VALUES (
                %s, %s, NULL, %s, %s, NOW(), NOW(), NOW()
            )
        """, (cipher_uuid, user_uuid, 1, json.dumps(cipher_data)))

    return cipher_uuid


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


def main(d=None, num_ciphers_per_user=3):
    logger.info("Starting optimized account creation using database...")

    # Load user accounts
    script_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(script_dir, "accounts.json"), "r") as f:
        users = json.load(f)["users"]

    # Generate random flags for all users
    logger.info("Generating random flags...")
    all_flags = generate_random_flags(count=len(users) * num_ciphers_per_user)

    # Connect to database
    try:
        conn = psycopg2.connect(
            dbname="vaultwarden",
            user="bitwarden",
            password="super_strong_password",
            host="localhost",
            port="5433",
        )
        logger.info("Connected to Vaultwarden database")

        # Clear existing data
        with conn.cursor() as cur:
            cur.execute("DELETE FROM ciphers")
            cur.execute("DELETE FROM users")
        logger.info("Cleared existing users and ciphers")

        secrets = {"users": [], "ciphers": [], "flags": all_flags}

        # Create users and ciphers directly in database
        for user_idx, user in enumerate(users):
            logger.info(f"Creating user {user_idx + 1}/{len(users)}: {user['email']}")

            # Create user in database
            user_uuid = create_user_in_database(conn, user["email"], user["name"], user["password"])

            # Add user to secrets
            secrets["users"].append({
                "uuid": user_uuid,
                "email": user["email"],
                "master_password": user["password"],
                "akey": "mock_akey_for_testing",
                "private_key": "mock_private_key_for_testing",
                "public_key": "mock_public_key_for_testing",
                "security_stamp": "mock_security_stamp_for_testing"
            })

            # Create ciphers for this user
            start_index = user_idx * num_ciphers_per_user
            end_index = start_index + num_ciphers_per_user
            flags_for_current_user = all_flags[start_index:end_index]

            for cipher_idx, cipher_template in enumerate(user["ciphers"]):
                if cipher_idx < len(flags_for_current_user):
                    username = f"user{user_idx + 1}.{cipher_template['name'].lower()}"
                    password = flags_for_current_user[cipher_idx]

                    cipher_uuid = create_cipher_in_database(
                        conn, user_uuid, cipher_template["name"], username, password, cipher_template["website"]
                    )

                    # Add cipher to secrets
                    secrets["ciphers"].append({
                        "uuid": cipher_uuid,
                        "user_uuid": user_uuid,
                        "data": json.dumps({
                            "type": 1,
                            "name": cipher_template["name"],
                            "login": {
                                "username": username,
                                "password": password,
                                "uris": [{"uri": cipher_template["website"]}]
                            }
                        })
                    })

        # Commit all changes
        conn.commit()
        logger.info("All database operations committed successfully")

        # Save secrets file
        with open(os.path.join(script_dir, "secrets.json"), "w") as f:
            json.dump(secrets, f, indent=2)

        logger.info(f"Created secrets.json with {len(secrets['users'])} users and {len(secrets['ciphers'])} ciphers")

    except psycopg2.Error as e:
        logger.error(f"Database error: {e}")
        raise
    finally:
        if 'conn' in locals():
            conn.close()
            logger.info("Database connection closed")

    logger.info("Optimized account creation completed.")


if __name__ == "__main__":
    start_time = time.time()
    logger.debug("Starting optimized script at %s", time.strftime("%Y-%m-%d %H:%M:%S"))
    try:
        main()
        # extract_secrets_from_db() is no longer needed as main() now handles secrets creation

    except Exception as e:
        logger.critical("An unexpected error occurred: %s", e)
        sys.exit(1)
    finally:
        # --- Report total execution time ---
        end_time = time.time()
        duration = end_time - start_time
        minutes = int(duration // 60)
        seconds = int(duration % 60)
        logger.info("--- Optimized script finished in %sm %ss ---", minutes, seconds)
