#!/usr/bin/env python3
"""
SimpleLogin data seeder for MobileCybench testing.
Creates deterministic test credentials, API tokens, and database users without requiring live authentication.
"""

import hashlib
import json
from pathlib import Path


def generate_deterministic_token(email, password, device="mobilecybench-test"):
    """Generate a deterministic but realistic API token"""
    seed_string = f"{email}:{password}:{device}:simplelogin-api-key"
    seed_hash = hashlib.sha256(seed_string.encode()).hexdigest()

    token_chars = "abcdefghijklmnopqrstuvwxyz0123456789"
    token = ""
    for i in range(32):
        char_index = int(seed_hash[i * 2 : i * 2 + 2], 16) % len(token_chars)
        token += token_chars[char_index]

    return f"sl_{token}"


def generate_user_data():
    """Generate multiple test users with deterministic auth tokens."""
    users = [
        {
            "username": "user_a",
            "email": "testuser@gmail.com",
            "password": "Passw0rd123",
            "display_name": "Test User A",
            "user_id": "1001",
            "is_admin": False,
        },
        {
            "username": "user_b",
            "email": "user2@simplelogin.test",
            "password": "Test456abc",
            "display_name": "Test User B",
            "user_id": "1002",
            "is_admin": False,
        },
        {
            "username": "admin_user",
            "email": "admin@simplelogin.test",
            "password": "Admin789abc",
            "display_name": "Admin User",
            "user_id": "1003",
            "is_admin": True,
        },
    ]

    for user in users:
        user["auth_token"] = generate_deterministic_token(
            user["email"], user["password"]
        )

    return users


def get_db_container_name():
    try:
        metadata = json.loads(
            (Path(__file__).resolve().parent / "metadata.json").read_text()
        )
        for name in metadata.get("container_names", []):
            if "db" in name:
                return name
    except Exception:
        pass
    return "simplelogin-db"


def create_users_in_database(users):
    """Create users directly in the database (bypassing API registration)."""
    import subprocess

    try:
        import bcrypt
    except ImportError:
        print("bcrypt module not available - install with: pip3 install bcrypt")
        return False

    try:
        sql_commands = ""

        for user in users:
            email = user["email"]
            password = user["password"]
            api_token = user["auth_token"]
            is_admin = user["is_admin"]

            # Hash the password using bcrypt (same as SimpleLogin's set_password)
            salt = bcrypt.gensalt()
            password_hash = bcrypt.hashpw(password.encode("utf-8"), salt).decode(
                "utf-8"
            )
            salt_str = salt.decode("utf-8")

            sql_commands += f"""
            INSERT INTO users (email, password, salt, activated, created_at, updated_at, is_admin)
            VALUES ('{email}', '{password_hash}', '{salt_str}', true, NOW(), NOW(), {is_admin})
            ON CONFLICT (email) DO UPDATE SET
                password = EXCLUDED.password,
                salt = EXCLUDED.salt,
                activated = true,
                updated_at = NOW(),
                is_admin = EXCLUDED.is_admin;

            INSERT INTO api_key (user_id, code, name, created_at, times)
            SELECT users.id, '{api_token}', 'mobilecybench-test', NOW(), 0
            FROM users WHERE email = '{email}'
            ON CONFLICT (code) DO UPDATE SET
                user_id = EXCLUDED.user_id,
                name = EXCLUDED.name,
                created_at = NOW(),
                times = 0;
            """

        cmd = [
            "docker",
            "exec",
            "-i",
            get_db_container_name(),
            "psql",
            "-U",
            "simplelogin",
            "-d",
            "simplelogin",
            "-c",
            sql_commands,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode == 0:
            print(f"{len(users)} users created/updated in database")
            return True
        else:
            print(f"Database operation failed: {result.stderr}")
            return False

    except Exception as e:
        print(f"Error creating users in database: {e}")
        return False


def main():
    users = generate_user_data()
    print(f"Creating {len(users)} users in database...")
    create_users_in_database(users)


if __name__ == "__main__":
    main()
