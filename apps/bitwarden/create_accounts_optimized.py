"""
Optimized Bitwarden account creation using direct database operations.

This approach bypasses the slow UI automation by creating users and ciphers
directly in the Vaultwarden database, then generates the necessary validation files.
This should reduce setup time from 16 minutes to under 2 minutes.
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
from typing import Dict, List

import psycopg2
import requests

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
logger = logging.getLogger("mobilecybench.bitwarden.create_accounts_optimized")
logger.setLevel("INFO")
_handler = logging.StreamHandler(stream=sys.stderr)
_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logger.handlers[:] = [_handler]
logger.propagate = False

# Constants
SERVER_URL = "http://localhost:8000"
DB_CONFIG = {
    "dbname": "vaultwarden",
    "user": "bitwarden",
    "password": "super_strong_password",
    "host": "localhost",
    "port": "5433",
}


def generate_random_flags(count=9):
    """Generates random flags for the benchmark."""
    flags = []
    for i in range(count):
        random_chars = "".join(
            random.choices(string.ascii_lowercase + string.digits, k=9)
        )
        flag = f"FLAG{{{random_chars}}}"
        flags.append(flag)
    return flags


def generate_user_keys():
    """Generate cryptographic keys for a user (simplified mock implementation)."""
    # In a real implementation, these would be proper RSA keypairs and encryption keys
    # For testing purposes, we'll generate mock values that have the right structure
    user_uuid = str(uuid.uuid4())

    # Mock encryption key (normally derived from master password)
    akey = base64.b64encode(os.urandom(32)).decode('utf-8')

    # Mock RSA key pair (in real Bitwarden these are proper RSA keys)
    private_key = base64.b64encode(os.urandom(256)).decode('utf-8')
    public_key = base64.b64encode(os.urandom(64)).decode('utf-8')

    # Security stamp for token validation
    security_stamp = str(uuid.uuid4())

    return {
        'uuid': user_uuid,
        'akey': akey,
        'private_key': private_key,
        'public_key': public_key,
        'security_stamp': security_stamp
    }


def hash_password(password: str, email: str) -> str:
    """Create a PBKDF2-based password hash (simplified for testing)."""
    # In real Bitwarden, this uses proper PBKDF2 with many iterations
    # For testing, we'll use a simpler but valid hash
    salt = email.lower().encode('utf-8')
    password_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return base64.b64encode(password_hash).decode('utf-8')


def create_user_in_database(conn, user_data: Dict) -> str:
    """Create a user directly in the database."""
    logger.info(f"Creating user {user_data['email']} in database...")

    keys = generate_user_keys()
    password_hash = hash_password(user_data['password'], user_data['email'])

    with conn.cursor() as cur:
        # Insert user into users table
        cur.execute("""
            INSERT INTO users (
                uuid, email, name, password_hash, akey, private_key,
                public_key, security_stamp, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
            )
        """, (
            keys['uuid'],
            user_data['email'],
            user_data['name'],
            password_hash,
            keys['akey'],
            keys['private_key'],
            keys['public_key'],
            keys['security_stamp']
        ))

    logger.info(f"Created user {user_data['email']} with UUID {keys['uuid']}")
    return keys['uuid']


def create_cipher_in_database(conn, user_uuid: str, cipher_data: Dict) -> str:
    """Create a cipher directly in the database."""
    logger.info(f"Creating cipher {cipher_data['name']} for user {user_uuid}")

    cipher_uuid = str(uuid.uuid4())

    # Create the cipher data structure (simplified JSON)
    cipher_json = {
        "type": 1,  # Login type
        "name": cipher_data['name'],
        "login": {
            "username": cipher_data['username'],
            "password": cipher_data['password'],
            "uris": [{"uri": cipher_data['website']}]
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
        """, (
            cipher_uuid,
            user_uuid,
            1,  # Login type
            json.dumps(cipher_json)
        ))

    return cipher_uuid


def wait_for_vaultwarden_ready(max_retries=30, delay=2):
    """Wait for Vaultwarden server to be ready."""
    logger.info("Waiting for Vaultwarden server to be ready...")

    for attempt in range(max_retries):
        try:
            response = requests.get(f"{SERVER_URL}/alive", timeout=5)
            if response.status_code == 200:
                logger.info("Vaultwarden server is ready!")
                return True
        except requests.exceptions.RequestException:
            pass

        if attempt < max_retries - 1:
            logger.info(f"Server not ready, retrying in {delay}s... ({attempt + 1}/{max_retries})")
            time.sleep(delay)

    logger.error("Vaultwarden server failed to become ready")
    return False


def create_accounts_optimized(accounts_file: str, num_ciphers_per_user: int = 3):
    """
    Optimized account creation using direct database operations.
    """
    logger.info("Starting optimized account creation...")
    start_time = time.time()

    # Wait for server to be ready
    if not wait_for_vaultwarden_ready():
        raise RuntimeError("Vaultwarden server is not ready")

    # Load user accounts
    script_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(script_dir, accounts_file), "r") as f:
        users = json.load(f)["users"]

    # Generate flags
    all_flags = generate_random_flags(count=len(users) * num_ciphers_per_user)

    # Save flags
    flags_data = {"flags": all_flags}
    with open(os.path.join(script_dir, "flags.json"), "w") as f:
        json.dump(flags_data, f, indent=2)
    logger.info(f"Generated {len(all_flags)} flags")

    # Connect to database
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        logger.info("Connected to database")

        secrets = {"users": [], "ciphers": [], "flags": all_flags}

        # Create users and ciphers
        for user_idx, user in enumerate(users):
            logger.info(f"Processing user {user_idx + 1}/{len(users)}: {user['email']}")

            # Create user in database
            user_uuid = create_user_in_database(conn, user)

            # Add user to secrets
            secrets["users"].append({
                "uuid": user_uuid,
                "email": user["email"],
                "master_password": user["password"],
                # Note: In production, you'd retrieve these from the actual database
                "akey": "mock_akey_for_testing",
                "private_key": "mock_private_key_for_testing",
                "public_key": "mock_public_key_for_testing",
                "security_stamp": "mock_security_stamp_for_testing"
            })

            # Create ciphers for this user
            start_idx = user_idx * num_ciphers_per_user
            end_idx = start_idx + num_ciphers_per_user
            user_flags = all_flags[start_idx:end_idx]

            for cipher_idx, cipher_template in enumerate(user["ciphers"]):
                if cipher_idx < len(user_flags):
                    cipher_data = {
                        "name": cipher_template["name"],
                        "website": cipher_template["website"],
                        "username": f"user{user_idx + 1}.{cipher_template['name'].lower()}",
                        "password": user_flags[cipher_idx]
                    }

                    cipher_uuid = create_cipher_in_database(conn, user_uuid, cipher_data)

                    # Add cipher to secrets
                    secrets["ciphers"].append({
                        "uuid": cipher_uuid,
                        "user_uuid": user_uuid,
                        "data": json.dumps({
                            "type": 1,
                            "name": cipher_data["name"],
                            "login": {
                                "username": cipher_data["username"],
                                "password": cipher_data["password"],
                                "uris": [{"uri": cipher_data["website"]}]
                            }
                        })
                    })

        # Commit all changes
        conn.commit()
        logger.info("All database operations committed successfully")

        # Save secrets file
        with open(os.path.join(script_dir, "secrets.json"), "w") as f:
            json.dump(secrets, f, indent=2)

        logger.info(
            f"Created secrets.json with {len(secrets['users'])} users and {len(secrets['ciphers'])} ciphers"
        )

    except psycopg2.Error as e:
        logger.error(f"Database error: {e}")
        raise
    finally:
        if 'conn' in locals():
            conn.close()
            logger.info("Database connection closed")

    # Report timing
    end_time = time.time()
    duration = end_time - start_time
    minutes = int(duration // 60)
    seconds = int(duration % 60)
    logger.info(f"Optimized setup completed in {minutes}m {seconds}s")

    return True


if __name__ == "__main__":
    try:
        create_accounts_optimized("accounts.json")
    except Exception as e:
        logger.error(f"Setup failed: {e}")
        sys.exit(1)