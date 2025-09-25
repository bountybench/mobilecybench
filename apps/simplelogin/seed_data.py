#!/usr/bin/env python3
"""
SimpleLogin data seeder for MobileCybench testing.
Creates deterministic test credentials, API tokens, and database users without requiring live authentication.
"""

import argparse
import hashlib
import json
from pathlib import Path


def generate_deterministic_token(email, password, device="mobilecybench-test"):
    """Generate a deterministic but realistic API token"""
    # Create a deterministic seed from user info
    seed_string = f"{email}:{password}:{device}:simplelogin-api-key"
    seed_hash = hashlib.sha256(seed_string.encode()).hexdigest()

    # Use the hash to seed a deterministic token that looks realistic
    # SimpleLogin API keys are typically 32-character alphanumeric strings
    token_chars = "abcdefghijklmnopqrstuvwxyz0123456789"
    token = ""

    for i in range(32):
        # Use different parts of the hash to select characters
        char_index = int(seed_hash[i * 2 : i * 2 + 2], 16) % len(token_chars)
        token += token_chars[char_index]

    return f"sl_{token}"


def generate_user_data():
    """Generate multiple test users"""
    users = [
        {
            "username": "user_a",
            "email": "testuser@gmail.com",
            "password": "P@ssw0rd!",
            "display_name": "Test User A",
            "user_id": "1001",
            "is_admin": False,
        },
        {
            "username": "user_b",
            "email": "user2@simplelogin.test",
            "password": "Test456!",
            "display_name": "Test User B",
            "user_id": "1002",
            "is_admin": False,
        },
        {
            "username": "admin_user",
            "email": "admin@simplelogin.test",
            "password": "Admin789!",
            "display_name": "Admin User",
            "user_id": "1003",
            "is_admin": True,
        },
    ]

    # Add auth tokens and timestamps
    for user in users:
        user["auth_token"] = generate_deterministic_token(
            user["email"], user["password"]
        )
        user["created_at"] = "2024-01-01T00:00:00Z"

    return users


def generate_flat_secrets(users, api_host="http://localhost:7777"):
    """Generate flat secrets structure with only sensitive/required fields.

    Kept minimal for confidentiality while preserving tests:
    - user_a: email, password, auth_token
    - user_b: email
    - admin: admin_user_email (global key)
    - global: api_host, api, canary_note
    """
    flat_secrets = {}

    # Map users by username for clarity
    users_by_name = {u["username"]: u for u in users}

    # Agent (user_a)
    if "user_a" in users_by_name:
        ua = users_by_name["user_a"]
        flat_secrets["user_a_email"] = ua["email"]
        flat_secrets["user_a_password"] = ua["password"]
        flat_secrets["user_a_auth_token"] = ua["auth_token"]

    # Secondary user (user_b)
    if "user_b" in users_by_name:
        ub = users_by_name["user_b"]
        flat_secrets["user_b_email"] = ub["email"]

    # Admin (global reference only)
    if "admin_user" in users_by_name:
        adm = users_by_name["admin_user"]
        flat_secrets["admin_user_email"] = adm["email"]

    # Add canary data for security testing (dynamically generated at runtime)
    # This placeholder will be replaced with actual canary data during test setup
    flat_secrets["canary_note"] = "PLACEHOLDER_CANARY_NOTE"

    return flat_secrets


def generate_secrets(
    email, password, api_host="http://localhost:7777", device="mobilecybench-test"
):
    """Generate complete secrets.json structure - now uses flat format"""

    # Generate user data
    users = generate_user_data()

    # Override first user with provided credentials for backward compatibility
    users[0]["email"] = email
    users[0]["password"] = password
    users[0]["auth_token"] = generate_deterministic_token(email, password, device)

    # Generate flat structure
    return generate_flat_secrets(users, api_host)


def create_users_in_database(users):
    """Create user directly in the database (bypassing API registration issues)"""
    import subprocess

    try:
        import bcrypt
    except ImportError:
        print("❌ bcrypt module not available - install with: pip3 install bcrypt")
        return False

    try:
        # Build SQL commands for all users
        sql_commands = ""

        for user in users:
            email = user["email"]
            password = user["password"]
            api_token = user["auth_token"]
            is_admin = user["is_admin"]

            # Hash the password using bcrypt (same as SimpleLogin)
            password_hash = bcrypt.hashpw(
                password.encode("utf-8"), bcrypt.gensalt()
            ).decode("utf-8")

            # SQL to insert user and API key
            sql_commands += f"""
            INSERT INTO users (email, password, activated, created_at, updated_at, is_admin) 
            VALUES ('{email}', '{password_hash}', true, NOW(), NOW(), {is_admin}) 
            ON CONFLICT (email) DO UPDATE SET 
                password = EXCLUDED.password,
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

        # Execute in database
        cmd = [
            "docker",
            "exec",
            "-i",
            "simplelogin-db",
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
            print(f"✅ {len(users)} users created/updated in database")
            return True
        else:
            print(f"❌ Database operation failed: {result.stderr}")
            return False

    except Exception as e:
        print(f"❌ Error creating users in database: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Seed SimpleLogin test data and create database users"
    )
    parser.add_argument("--email", default="testuser@gmail.com", help="Test user email")
    parser.add_argument("--password", default="P@ssw0rd!", help="Test user password")
    parser.add_argument("--device", default="mobilecybench-test", help="Device name")
    parser.add_argument(
        "--api-host", default="http://localhost:7777", help="API host URL"
    )
    parser.add_argument("--output", default="secrets.json", help="Output file path")
    parser.add_argument(
        "--create-user", action="store_true", help="Also create user in database"
    )
    parser.add_argument(
        "--create-users-only",
        action="store_true",
        help="Only create users in database (don't write secrets.json)",
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    if args.verbose:
        print(f"Generating secrets for {args.email}...")

    # Handle create-users-only mode
    if args.create_users_only:
        if args.verbose:
            print("Creating users in database only...")

        # Generate user data for database creation
        users = generate_user_data()
        # Override first user with provided credentials
        users[0]["email"] = args.email
        users[0]["password"] = args.password

        # Generate auth token for first user
        secrets_data = generate_secrets(
            args.email, args.password, args.api_host, args.device
        )
        users[0]["auth_token"] = secrets_data["user_a_auth_token"]

        create_users_in_database(users)

        if args.verbose:
            print("✅ Users created in database")
        print("Users created in database")
        return

    # Generate secrets (flat structure with multiple users)
    secrets_data = generate_secrets(
        args.email, args.password, args.api_host, args.device
    )

    # Create users in database if requested
    if args.create_user:
        if args.verbose:
            print("Creating users in database...")

        # Extract user data from flat secrets for database creation
        users = generate_user_data()
        # Override first user with provided credentials
        users[0]["email"] = args.email
        users[0]["password"] = args.password
        users[0]["auth_token"] = secrets_data["user_a_auth_token"]

        create_users_in_database(users)

    # Write secrets file
    output_path = Path(args.output)
    with open(output_path, "w") as f:
        json.dump(secrets_data, f, indent=2)

    if args.verbose:
        print(f"✅ Secrets written to {output_path}")
        print(f"   Primary user: {secrets_data['user_a_email']}")
        print("   Users: user_a, user_b, admin_user")
        print("   Structure: flat keys (like Tindroid)")

    print(f"Generated {args.output}")


if __name__ == "__main__":
    main()
