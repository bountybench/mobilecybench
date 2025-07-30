#!/usr/bin/env python3
"""
Parse dump.sql and create secrets.json with sensitive data for confidentiality checks.

This script should be run after create_accounts_ui.py has finished and created dump.sql.
"""

import json
import re
import sys

def parse_dump_and_create_secrets():
    """Parse dump.sql and create secrets.json with sensitive data for confidentiality checks."""
    print("Parsing database dump for sensitive data...")

    secrets = {
        "users": [],
        "ciphers": [],
        "flags": []
    }

    try:
        # Load the flags that were generated
        with open('flags.json', 'r') as f:
            flags_data = json.load(f)
            secrets["flags"] = flags_data["flags"]

        # Load the original user data from accounts.json to get the correct mapping
        with open('accounts.json', 'r') as f:
            original_users = json.load(f)['users']

        # Create a mapping from email to original user object for correct alignment
        email_to_original_user = {user['email']: user for user in original_users}

        # Parse the dump.sql file to extract user data
        with open('dump.sql', 'r') as f:
            dump_content = f.read()

        # Extract user data from the users table using COPY format
        user_copy_pattern = r"COPY public\.users \(.*?\) FROM stdin;\n(.*?)\\\.\n"
        user_matches = re.findall(user_copy_pattern, dump_content, re.DOTALL)

        if user_matches:
            user_lines = user_matches[0].strip().split('\n')
            for line in user_lines:
                if not line.strip():
                    continue
                values = line.split('\t')
                if len(values) >= 16: # Ensure we have enough fields up to security_stamp
                    email = values[3].strip()
                    original_user = email_to_original_user.get(email)
                    if original_user:
                        user_entry = {
                            "email": email,
                            "master_password": original_user['password'],
                            "uuid": values[0].strip(),
                            "akey": values[9].strip(),
                            "private_key": values[10].strip(),
                            "public_key": values[11].strip(),
                            "security_stamp": values[14].strip(),
                        }
                        secrets["users"].append(user_entry)

        # Extract cipher data and link it to users
        cipher_copy_pattern = r"COPY public\.ciphers \(.*?\) FROM stdin;\n(.*?)\\\.\n"
        cipher_matches = re.findall(cipher_copy_pattern, dump_content, re.DOTALL)

        if cipher_matches:
            cipher_lines = cipher_matches[0].strip().split('\n')
            for cipher_line in cipher_lines:
                if not cipher_line.strip():
                    continue
                values = cipher_line.split('\t')
                if len(values) >= 10: # Ensure we have enough fields up to data
                    secrets["ciphers"].append({
                        "uuid": values[0].strip(),
                        "user_uuid": values[3].strip(),
                        "data": values[9].strip(),
                    })

        # Write secrets to file
        with open('secrets.json', 'w') as f:
            json.dump(secrets, f, indent=2)

        print(f"Created secrets.json with {len(secrets['users'])} users and {len(secrets['ciphers'])} ciphers.")
        return True

    except Exception as e:
        print(f"[ERROR] Failed to parse dump and create secrets: {e}", file=sys.stderr)
        return False

if __name__ == "__main__":
    if parse_dump_and_create_secrets():
        print("Secrets file created successfully for confidentiality checks.")
        sys.exit(0)
    else:
        print("Failed to create secrets file.")
        sys.exit(1) 