"""
Database setup utilities for Vaultwarden.

This module provides functions to directly interact with the Vaultwarden database
for faster account and cipher creation, bypassing the UI automation layer.
"""

import json
import logging
import os
import sys
import time
import hashlib
import base64
import uuid
import random
import string
from typing import Dict, List, Optional, Tuple

import psycopg2
import requests


logger = logging.getLogger("mobilecybench.bitwarden.database_setup")


class VaultwardenDBManager:
    """Manager for Vaultwarden database operations."""

    def __init__(self, db_config: Dict[str, str], server_url: str = "http://localhost:8000"):
        self.db_config = db_config
        self.server_url = server_url
        self.conn = None

    def connect(self):
        """Connect to the database."""
        try:
            self.conn = psycopg2.connect(**self.db_config)
            logger.info("Connected to Vaultwarden database")
            return True
        except psycopg2.Error as e:
            logger.error(f"Failed to connect to database: {e}")
            return False

    def disconnect(self):
        """Disconnect from the database."""
        if self.conn:
            self.conn.close()
            logger.info("Disconnected from database")

    def wait_for_server(self, max_retries: int = 30, delay: int = 2) -> bool:
        """Wait for Vaultwarden server to be ready."""
        logger.info("Waiting for Vaultwarden server to be ready...")

        for attempt in range(max_retries):
            try:
                response = requests.get(f"{self.server_url}/alive", timeout=5)
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

    def clear_existing_data(self) -> bool:
        """Clear existing users and ciphers from database."""
        if not self.conn:
            return False

        try:
            with self.conn.cursor() as cur:
                # Delete in correct order due to foreign key constraints
                cur.execute("DELETE FROM ciphers")
                cur.execute("DELETE FROM users")
                self.conn.commit()
                logger.info("Cleared existing users and ciphers from database")
                return True
        except psycopg2.Error as e:
            logger.error(f"Failed to clear existing data: {e}")
            if self.conn:
                self.conn.rollback()
            return False

    def create_user_direct(self, email: str, name: str, password: str) -> Optional[str]:
        """
        Create a user directly in the database.
        Returns the user UUID if successful, None otherwise.
        """
        if not self.conn:
            return None

        try:
            user_uuid = str(uuid.uuid4())
            security_stamp = str(uuid.uuid4())

            # Generate simplified keys for testing
            # In production, these would be proper cryptographic keys
            akey = base64.b64encode(os.urandom(32)).decode('utf-8')
            private_key = base64.b64encode(os.urandom(256)).decode('utf-8')
            public_key = base64.b64encode(os.urandom(64)).decode('utf-8')

            # Create a simple password hash
            # In production, this would use proper PBKDF2 with many iterations
            salt = email.lower().encode('utf-8')
            password_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
            password_hash_b64 = base64.b64encode(password_hash).decode('utf-8')

            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO users (
                        uuid, email, name, password_hash, akey, private_key,
                        public_key, security_stamp, created_at, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
                    )
                """, (
                    user_uuid, email, name, password_hash_b64,
                    akey, private_key, public_key, security_stamp
                ))

            logger.info(f"Created user {email} with UUID {user_uuid}")
            return user_uuid

        except psycopg2.Error as e:
            logger.error(f"Failed to create user {email}: {e}")
            return None

    def create_cipher_direct(self, user_uuid: str, name: str, username: str,
                           password: str, website: str) -> Optional[str]:
        """
        Create a cipher directly in the database.
        Returns the cipher UUID if successful, None otherwise.
        """
        if not self.conn:
            return None

        try:
            cipher_uuid = str(uuid.uuid4())

            # Create the cipher data structure
            cipher_data = {
                "type": 1,  # Login type
                "name": name,
                "login": {
                    "username": username,
                    "password": password,
                    "uris": [{"uri": website}] if website else []
                },
                "notes": None,
                "fields": None
            }

            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO ciphers (
                        uuid, user_uuid, organization_uuid, type, data,
                        created_at, updated_at, revision_date
                    ) VALUES (
                        %s, %s, NULL, %s, %s, NOW(), NOW(), NOW()
                    )
                """, (
                    cipher_uuid, user_uuid, 1, json.dumps(cipher_data)
                ))

            logger.info(f"Created cipher {name} for user {user_uuid}")
            return cipher_uuid

        except psycopg2.Error as e:
            logger.error(f"Failed to create cipher {name}: {e}")
            return None

    def get_all_users(self) -> List[Dict]:
        """Retrieve all users from the database."""
        if not self.conn:
            return []

        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT uuid, email, name, password_hash, akey,
                           private_key, public_key, security_stamp
                    FROM users ORDER BY email
                """)
                users = []
                for row in cur.fetchall():
                    users.append({
                        'uuid': row[0],
                        'email': row[1],
                        'name': row[2],
                        'password_hash': row[3],
                        'akey': row[4],
                        'private_key': row[5],
                        'public_key': row[6],
                        'security_stamp': row[7]
                    })
                return users
        except psycopg2.Error as e:
            logger.error(f"Failed to retrieve users: {e}")
            return []

    def get_all_ciphers(self) -> List[Dict]:
        """Retrieve all ciphers from the database."""
        if not self.conn:
            return []

        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT uuid, user_uuid, data
                    FROM ciphers ORDER BY user_uuid
                """)
                ciphers = []
                for row in cur.fetchall():
                    ciphers.append({
                        'uuid': row[0],
                        'user_uuid': row[1],
                        'data': row[2]
                    })
                return ciphers
        except psycopg2.Error as e:
            logger.error(f"Failed to retrieve ciphers: {e}")
            return []

    def commit(self):
        """Commit the current transaction."""
        if self.conn:
            self.conn.commit()

    def rollback(self):
        """Rollback the current transaction."""
        if self.conn:
            self.conn.rollback()


def generate_test_flags(count: int) -> List[str]:
    """Generate random flags for testing."""
    flags = []
    for _ in range(count):
        random_chars = "".join(
            random.choices(string.ascii_lowercase + string.digits, k=9)
        )
        flags.append(f"FLAG{{{random_chars}}}")
    return flags


def setup_accounts_via_database(accounts_file: str, clear_existing: bool = True,
                               num_ciphers_per_user: int = 3) -> Tuple[bool, str]:
    """
    Set up Bitwarden accounts using direct database manipulation.

    Args:
        accounts_file: Path to accounts.json file
        clear_existing: Whether to clear existing data first
        num_ciphers_per_user: Number of ciphers to create per user

    Returns:
        Tuple of (success: bool, message: str)
    """
    db_config = {
        "dbname": "vaultwarden",
        "user": "bitwarden",
        "password": "super_strong_password",
        "host": "localhost",
        "port": "5433",
    }

    db_manager = VaultwardenDBManager(db_config)
    start_time = time.time()

    try:
        # Wait for server to be ready
        if not db_manager.wait_for_server():
            return False, "Vaultwarden server is not ready"

        # Connect to database
        if not db_manager.connect():
            return False, "Failed to connect to database"

        # Clear existing data if requested
        if clear_existing:
            if not db_manager.clear_existing_data():
                return False, "Failed to clear existing data"

        # Load accounts
        script_dir = os.path.dirname(os.path.abspath(__file__))
        accounts_path = os.path.join(script_dir, accounts_file)

        with open(accounts_path, 'r') as f:
            accounts_data = json.load(f)
            users = accounts_data['users']

        # Generate flags
        total_flags_needed = len(users) * num_ciphers_per_user
        flags = generate_test_flags(total_flags_needed)

        # Save flags to file
        flags_data = {"flags": flags}
        with open(os.path.join(script_dir, "flags.json"), "w") as f:
            json.dump(flags_data, f, indent=2)

        # Create users and ciphers
        secrets = {"users": [], "ciphers": [], "flags": flags}
        created_users = 0
        created_ciphers = 0

        for user_idx, user in enumerate(users):
            logger.info(f"Creating user {user_idx + 1}/{len(users)}: {user['email']}")

            # Create user
            user_uuid = db_manager.create_user_direct(
                user['email'], user['name'], user['password']
            )

            if not user_uuid:
                return False, f"Failed to create user {user['email']}"

            created_users += 1

            # Add to secrets (with original password for validation)
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
            start_idx = user_idx * num_ciphers_per_user
            user_flags = flags[start_idx:start_idx + num_ciphers_per_user]

            for cipher_idx, cipher_template in enumerate(user.get('ciphers', [])):
                if cipher_idx >= num_ciphers_per_user:
                    break

                username = f"user{user_idx + 1}.{cipher_template['name'].lower()}"
                password = user_flags[cipher_idx] if cipher_idx < len(user_flags) else "DefaultPassword123!"

                cipher_uuid = db_manager.create_cipher_direct(
                    user_uuid,
                    cipher_template['name'],
                    username,
                    password,
                    cipher_template.get('website', '')
                )

                if cipher_uuid:
                    created_ciphers += 1
                    secrets["ciphers"].append({
                        "uuid": cipher_uuid,
                        "user_uuid": user_uuid,
                        "data": json.dumps({
                            "type": 1,
                            "name": cipher_template['name'],
                            "login": {
                                "username": username,
                                "password": password,
                                "uris": [{"uri": cipher_template.get('website', '')}]
                            }
                        })
                    })

        # Commit all changes
        db_manager.commit()

        # Save secrets file
        with open(os.path.join(script_dir, "secrets.json"), "w") as f:
            json.dump(secrets, f, indent=2)

        # Report results
        end_time = time.time()
        duration = end_time - start_time
        minutes = int(duration // 60)
        seconds = int(duration % 60)

        message = (f"Successfully created {created_users} users and {created_ciphers} ciphers "
                  f"in {minutes}m {seconds}s using database operations")

        logger.info(message)
        return True, message

    except Exception as e:
        error_msg = f"Database setup failed: {str(e)}"
        logger.error(error_msg)
        if db_manager.conn:
            db_manager.rollback()
        return False, error_msg

    finally:
        db_manager.disconnect()


if __name__ == "__main__":
    success, message = setup_accounts_via_database("accounts.json")
    print(message)
    sys.exit(0 if success else 1)