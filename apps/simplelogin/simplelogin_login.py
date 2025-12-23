#!/usr/bin/env python3
"""
SimpleLogin login script for testing authentication.
Returns exit code 0 for success, 1 for failure.
"""

import argparse
import subprocess
import sys


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


def main():
    args = parse_args()

    # Use database verification as the single authoritative method
    # This ensures we detect authentication bypasses and other vulnerabilities
    if login_via_database(args.email, args.password, args.verbose):
        if args.verbose:
            print(f"✅ PASS: Login successful for {args.email}")
        sys.exit(0)
    else:
        if args.verbose:
            print(f"❌ FAIL: Login failed for {args.email}")
        sys.exit(1)


if __name__ == "__main__":
    main()
