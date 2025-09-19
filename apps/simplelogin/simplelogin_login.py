#!/usr/bin/env python3
"""
SimpleLogin login script for testing authentication.
Returns exit code 0 for success, 1 for failure (like tindroid_login.py).
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="SimpleLogin login script")
    parser.add_argument("--email", required=True, help="User email")
    parser.add_argument("--password", required=True, help="User password")
    parser.add_argument(
        "--logout-after", action="store_true", help="Logout after login (compatibility)"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Print PASS/FAIL messages"
    )
    return parser.parse_args()


def load_secrets():
    """Load secrets from secrets.json file"""
    secrets_path = Path(__file__).parent / "secrets.json"
    if not secrets_path.exists():
        if parse_args().verbose:
            print("❌ FAIL: secrets.json not found")
        return None

    try:
        with open(secrets_path) as f:
            return json.load(f)
    except json.JSONDecodeError:
        if parse_args().verbose:
            print("❌ FAIL: Invalid JSON in secrets.json")
        return None


def get_user_data(secrets, email):
    """Get user data from flat secrets structure"""
    # Find the user by email in flat structure
    for key in secrets:
        if key.endswith("_email") and secrets[key] == email:
            username = key.replace("_email", "")
            return {
                "username": username,
                "email": secrets[f"{username}_email"],
                "password": secrets[f"{username}_password"],
                "auth_token": secrets[f"{username}_auth_token"],
                "user_id": secrets[f"{username}_user_id"],
            }
    return None


def login_via_database(email, password, verbose=False):
    """Login by verifying credentials directly in database (most reliable)"""
    try:
        # Get password hash from database
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
            "-t",
            "-c",
            f"SELECT password FROM users WHERE email='{email}' AND activated=true;",
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            if verbose:
                print(f"❌ FAIL: Database query failed: {result.stderr}")
            return False

        stored_hash = result.stdout.strip()
        if not stored_hash:
            if verbose:
                print(f"❌ FAIL: User {email} not found or not activated")
            return False

        # Verify password using bcrypt
        try:
            import bcrypt

            is_valid = bcrypt.checkpw(
                password.encode("utf-8"), stored_hash.encode("utf-8")
            )
            if verbose:
                if is_valid:
                    print(f"✅ PASS: Database login successful for {email}")
                else:
                    print(f"❌ FAIL: Password verification failed for {email}")
            return is_valid
        except ImportError:
            if verbose:
                print("❌ FAIL: bcrypt module not available")
            return False

    except subprocess.TimeoutExpired:
        if verbose:
            print("❌ FAIL: Database operation timed out")
        return False
    except Exception as e:
        if verbose:
            print(f"❌ FAIL: Database login error: {e}")
        return False


def login_via_secrets(email, password, verbose=False):
    """Login by comparing with secrets.json (fallback method)"""
    secrets = load_secrets()
    if not secrets:
        return False

    user_data = get_user_data(secrets, email)
    if not user_data:
        if verbose:
            print(f"❌ FAIL: User {email} not found in secrets")
        return False

    if user_data["password"] == password:
        if verbose:
            print(f"✅ PASS: Secrets login successful for {email}")
        return True
    else:
        if verbose:
            print(f"❌ FAIL: Password mismatch for {email}")
        return False


def main():
    args = parse_args()

    # Try database login first (most authoritative)
    if login_via_database(args.email, args.password, args.verbose):
        sys.exit(0)

    # Fallback to secrets comparison
    if login_via_secrets(args.email, args.password, args.verbose):
        sys.exit(0)

    # Both methods failed
    if args.verbose:
        print(f"❌ FAIL: All login methods failed for {args.email}")
    sys.exit(1)


if __name__ == "__main__":
    main()
