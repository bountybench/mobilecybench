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
    initialize_device_and_app,
    make_account,
    create_new_cipher,
    lock_and_logout,
    BITWARDEN_PKG
)

def generate_random_flags(count=15):
    """Generate random flags for the benchmark and save them to flags.json."""
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

def get_ciphers_for_user(user_data, flags_for_user, user_index):
    """Populate a user's cipher templates with dynamic usernames and passwords."""
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

def main(d, num_ciphers_per_user=5):
    # Load user accounts and their cipher templates from the unified JSON file
    with open('accounts.json', 'r') as f:
        users = json.load(f)['users']

    # Generate random flags for all users
    print("Generating random flags...")
    all_flags = generate_random_flags(count = len(users) * num_ciphers_per_user)

    # Initialize device and launch app
    initialize_device_and_app(d)

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

    print("Automation script finished.")

if __name__ == "__main__":
    start_time = time.time()
    d = None
    try:
        print("Connecting to device...")
        d = u2.connect()
        print("Connection successful.")

        main(d)

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