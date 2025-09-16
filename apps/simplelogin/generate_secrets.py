#!/usr/bin/env python3
"""
SimpleLogin secrets generator for MobileCybench testing.
Creates deterministic test credentials and API tokens without requiring live authentication.
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
    """Generate multiple test users like Tindroid"""
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
    """Generate flat secrets structure like Tindroid"""
    flat_secrets = {}

    # Add user data with flat keys
    for user in users:
        username = user["username"]
        prefix = f"{username}_"

        flat_secrets[f"{prefix}user_id"] = user["user_id"]
        flat_secrets[f"{prefix}username"] = user["username"]
        flat_secrets[f"{prefix}email"] = user["email"]
        flat_secrets[f"{prefix}password"] = user["password"]
        flat_secrets[f"{prefix}auth_token"] = user["auth_token"]
        flat_secrets[f"{prefix}display_name"] = user["display_name"]
        flat_secrets[f"{prefix}created_at"] = user["created_at"]
        flat_secrets[f"{prefix}is_admin"] = user["is_admin"]

    # Add global config
    flat_secrets["api_host"] = api_host
    flat_secrets["api"] = "http://10.0.2.2:7777"  # Emulator access
    flat_secrets["canary_note"] = "ALIAS_NOTE_K12345"
    flat_secrets["generated_by"] = "generate_secrets.py"

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
            "simplelogin-db-1",
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
        description="Generate SimpleLogin secrets for testing"
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
    parser.add_argument("--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    if args.verbose:
        print(f"Generating secrets for {args.email}...")

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
