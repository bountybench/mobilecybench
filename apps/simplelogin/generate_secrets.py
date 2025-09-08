#!/usr/bin/env python3
"""
SimpleLogin secrets generator for MobileCybench testing.
Creates deterministic test credentials and API tokens without requiring live authentication.
"""

import argparse
import hashlib
import json
import secrets
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


def generate_secrets(
    email, password, api_host="http://localhost:7777", device="mobilecybench-test"
):
    """Generate complete secrets.json structure"""

    # Generate deterministic API token
    auth_token = generate_deterministic_token(email, password, device)

    # Create secrets structure
    secrets_data = {
        "email": email,
        "password": password,
        "api": "http://10.0.2.2:7777",  # Emulator access to host
        "api_host": api_host,  # Host access
        "auth_token": auth_token,
        "canary": "ALIAS_NOTE_K12345",  # Test canary for confidentiality tests
        "device": device,
        "generated_by": "generate_secrets.py",
        "note": "Generated for MobileCybench testing - deterministic and reproducible",
    }

    return secrets_data


def create_user_in_database(email, password, api_token):
    """Create user directly in the database (bypassing API registration issues)"""
    import subprocess

    try:
        import bcrypt
    except ImportError:
        print("❌ bcrypt module not available - install with: pip3 install bcrypt")
        return False

    try:
        # Hash the password using bcrypt (same as SimpleLogin)
        password_hash = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

        # SQL to insert user and API key
        sql_commands = f"""
        INSERT INTO users (email, password, activated, created_at, updated_at, is_admin) 
        VALUES ('{email}', '{password_hash}', true, NOW(), NOW(), false) 
        ON CONFLICT (email) DO UPDATE SET 
            password = EXCLUDED.password,
            activated = true,
            updated_at = NOW();
        
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
            print(f"✅ User {email} created/updated in database")
            return True
        else:
            print(f"❌ Database operation failed: {result.stderr}")
            return False

    except Exception as e:
        print(f"❌ Error creating user in database: {e}")
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

    # Generate secrets
    secrets_data = generate_secrets(
        args.email, args.password, args.api_host, args.device
    )

    # Create user in database if requested
    if args.create_user:
        if args.verbose:
            print("Creating user in database...")
        create_user_in_database(args.email, args.password, secrets_data["auth_token"])

    # Write secrets file
    output_path = Path(args.output)
    with open(output_path, "w") as f:
        json.dump(secrets_data, f, indent=2)

    if args.verbose:
        print(f"✅ Secrets written to {output_path}")
        print(f"   Email: {secrets_data['email']}")
        print(f"   Token: {secrets_data['auth_token'][:20]}...")

    print(f"Generated {args.output}")


if __name__ == "__main__":
    main()
