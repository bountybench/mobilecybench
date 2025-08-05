"""
This script creates multiple Bitwarden accounts on a device.

This approach leverages the app itself to handle all the complex encryption, 
guaranteeing that the data is stored correctly.
"""

import uiautomator2 as u2
import time
import sys
import json
import random
import string
import subprocess
from util import (
    wait_for_ui_stable, 
    wait_and_click, 
    wait_and_set_text,
    initialize_local_host,
    make_account,
    create_new_cipher,
    lock_and_logout,
    BITWARDEN_PKG
)

"""
generate_random_flags()
- Generate random flags for the benchmark and save them to flags.json.
"""
def generate_random_flags(count=15):
    flags = []
    for i in range(count):
        # Generate random alphanumeric characters (9 chars for 16-char total with FLAG{} wrapper)
        random_chars = ''.join(random.choices(string.ascii_lowercase + string.digits, k=9))
        flag = f"FLAG{{{random_chars}}}"
        flags.append(flag)
    
    flags_data = {"flags": flags}
    
    with open('flags.json', 'w') as f:
        json.dump(flags_data, f, indent=2)
    
    print(f"Generated {len(flags)} random flags in flags.json")
    return flags

"""
get_ciphers_for_user()
- Populate a user's cipher templates with dynamic usernames and passwords.
"""
def get_ciphers_for_user(user_data, flags_for_user, user_index):
    base_ciphers = user_data['ciphers']
    
    # Add the user-specific flags and dynamic usernames to the ciphers
    for i, cipher in enumerate(base_ciphers):
        # Generate dynamic username, e.g., "user1.Amazon"
        cipher['username'] = f"user{user_index + 1}.{cipher['name'].lower()}"
        
        if i < len(flags_for_user):
            cipher['password'] = flags_for_user[i]
        else:
            # Fallback, though this should not be reached with correct slicing
            cipher['password'] = "SecurePassword123!" 
    
    return base_ciphers

"""
extract_secrets_from_db()
- Extract sensitive data from the database and create secrets.json.
"""
def extract_secrets_from_db():
    print("Extracting secrets from the database...")

    secrets = {
        "users": [],
        "ciphers": [],
        "flags": []
    }

    try:
        # 0. Load flags and accounts from json files
        with open('flags.json', 'r') as f:
            flags_data = json.load(f)
            secrets["flags"] = flags_data["flags"]

        with open('accounts.json', 'r') as f:
            original_users = json.load(f)['users']
        email_to_original_user = {user['email']: user for user in original_users}

        # 1. Extract user data from the database
        user_query = [
            "docker", "exec", "vaultwarden-db", "psql", "-U", "bitwarden", "-d", "vaultwarden",
            "-t", "-A", "-F", "\t",
            "-c", "SELECT uuid, email, akey, private_key, public_key, security_stamp FROM users;"
        ]
        user_result = subprocess.run(user_query, capture_output=True, text=True, check=True)
        for line in user_result.stdout.strip().split('\n'):
            if not line:
                continue
            values = line.split('\t')
            email = values[1]
            original_user = email_to_original_user.get(email)
            if original_user:
                secrets["users"].append({
                    "uuid": values[0],
                    "email": email,
                    "master_password": original_user['password'],
                    "akey": values[2],
                    "private_key": values[3],
                    "public_key": values[4],
                    "security_stamp": values[5],
                })

        # 2. Extract cipher data from the database
        cipher_query = [
            "docker", "exec", "vaultwarden-db", "psql", "-U", "bitwarden", "-d", "vaultwarden",
            "-t", "-A", "-F", "\t",
            "-c", "SELECT uuid, user_uuid, data FROM ciphers;"
        ]
        cipher_result = subprocess.run(cipher_query, capture_output=True, text=True, check=True)
        for line in cipher_result.stdout.strip().split('\n'):
            if not line:
                continue
            values = line.split('\t')
            secrets["ciphers"].append({
                "uuid": values[0],
                "user_uuid": values[1],
                "data": values[2],
            })

        # 3. Save the secrets to secrets.json
        with open('secrets.json', 'w') as f:
            json.dump(secrets, f, indent=2)

        print(f"Created secrets.json with {len(secrets['users'])} users and {len(secrets['ciphers'])} ciphers.")
        return True

    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[ERROR] Failed to extract secrets: {e}", file=sys.stderr)
        if isinstance(e, subprocess.CalledProcessError):
            print(f"[ERROR] psql command stderr:\n{e.stderr}", file=sys.stderr)
        return False


def main(d, num_ciphers_per_user=5):
    # Load user accounts and their cipher templates from the unified JSON file
    with open('accounts.json', 'r') as f:
        users = json.load(f)['users']

    # Generate random flags for all users
    print("Generating random flags...")
    all_flags = generate_random_flags(count = len(users) * num_ciphers_per_user)

    # Initialize device and launch app
    initialize_local_host(d)

    for user_idx, user in enumerate(users):
        # Create the account with provided credentials
        make_account(d, user['email'], user['name'], user['password'], user_idx)

        # Determine the slice of flags for the current user
        start_index = user_idx * num_ciphers_per_user
        end_index = start_index + num_ciphers_per_user
        flags_for_current_user = all_flags[start_index:end_index]

        # Get the list of ciphers populated with the correct flags and usernames
        ciphers_for_current_user = get_ciphers_for_user(user, flags_for_current_user, user_idx)

        # After creating an account, we are in the main vault.
        # Create the ciphers for the new user.
        print(f"=== Populating ciphers for {user['email']} with flags {start_index+1}-{end_index} ===")
        for cipher in ciphers_for_current_user:
            create_new_cipher(d, cipher)

        lock_and_logout(d)

    print("Accounts creation completed.")

if __name__ == "__main__":
    start_time = time.time()
    d = None
    try:
        print("Connecting to device...")
        d = u2.connect()
        print("Connection successful.")

        main(d)

        extract_secrets_from_db()

    except Exception as e:
        print(f"[FATAL] An unexpected error occurred: {e}", file=sys.stderr)
        if d:
            print("Dumping UI hierarchy for debugging:", file=sys.stderr)
            # print(d.dump_hierarchy(), file=sys.stderr)
        sys.exit(1)
    finally:
        # --- Create a database dump ---
        print("\nCreating database dump in dump.sql...")
        try:
            with open('dump.sql', 'w') as f:
                subprocess.run(
                    [
                        "docker", "exec", "bitwarden-db-1", 
                        "pg_dump", "-U", "bitwarden", "-d", "vaultwarden"
                    ], 
                    stdout=f, 
                    check=True
                )
            print("Database dump created successfully.")
                
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"[ERROR] Failed to create database dump: {e}", file=sys.stderr)
        
        # --- Clean up ---
        if d:
            print(f"Stopping app {BITWARDEN_PKG}...")
            d.app_stop(BITWARDEN_PKG)
        
        # --- Report total execution time ---
        end_time = time.time()
        duration = end_time - start_time
        minutes = int(duration // 60)
        seconds = int(duration % 60)
        print(f"\n--- Script finished in {minutes}m {seconds}s ---")
