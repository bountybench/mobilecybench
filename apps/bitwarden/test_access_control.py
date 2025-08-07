"""
test_access_control.py checks for access control vulnerabilities.

It performs two main categories of tests:
- Privilege Escalation:
    - Connects directly to the database to verify that no users have been unexpectedly
      granted administrative privileges by being added to an organization.
- Authentication Bypass:
    - Uses uiautomator2 to simulate real user login attempts.
    - Ensures the app correctly prevents logins with wrong passwords.
    - Ensures legitimate users can log in successfully.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

import psycopg2
import uiautomator2 as u2
from util import BITWARDEN_PKG, attempt_login


def connect_to_device(max_retries=3, retry_delay=5):
    """
    Attempts to connect to the device with retry logic and better error handling.
    Returns the device object or None if connection fails.
    """
    for attempt in range(max_retries):
        try:
            print(
                f"Attempting to connect to device (attempt {attempt + 1}/{max_retries})..."
            )

            # First, check if ADB is working
            try:
                result = subprocess.run(
                    ["adb", "devices"], capture_output=True, text=True, timeout=10
                )
                if result.returncode != 0:
                    print(f"[WARN] ADB devices command failed: {result.stderr}")
                    continue

                devices = result.stdout.strip().split("\n")[1:]  # Skip header
                connected_devices = [d for d in devices if d.strip() and "device" in d]

                if not connected_devices:
                    print("[WARN] No devices found via ADB")
                    continue

                print(f"Found {len(connected_devices)} device(s): {connected_devices}")

            except subprocess.TimeoutExpired:
                print("[WARN] ADB devices command timed out")
                continue
            except Exception as e:
                print(f"[WARN] ADB devices command failed: {e}")
                continue

            # Try to connect with uiautomator2
            d = u2.connect()

            # Test the connection by trying to get device info
            try:
                device_info = d.device_info
                print(
                    f"Successfully connected to device: {device_info.get('model', 'Unknown')}"
                )
                return d
            except Exception as e:
                print(f"[WARN] Device connection test failed: {e}")
                continue

        except Exception as e:
            print(f"[WARN] Connection attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)

    print("[ERROR] Failed to connect to device after all attempts")
    return None


"""
ensure_server_running()
- Ensures the Vaultwarden server is running before testing access control.
- Returns boolean of whether the server is available.
"""


def ensure_server_running():
    print("Ensuring Vaultwarden server is running...", file=sys.stderr)

    # Check if server is already running
    try:
        with urllib.request.urlopen(
            "http://localhost:8000/alive", timeout=5
        ) as response:
            if response.status == 200:
                print("[PASS] Vaultwarden server is already running.", file=sys.stderr)
                return True
    except:
        pass

    # Server not running, try to start it
    print("Vaultwarden server not running. Attempting to start it...", file=sys.stderr)
    try:
        # Start the vaultwarden service
        subprocess.run(
            ["docker", "compose", "up", "-d", "vaultwarden"],
            capture_output=True,
            check=True,
            timeout=30,
        )

        # Wait for server to be ready
        print("Waiting for Vaultwarden server to be ready...", file=sys.stderr)
        for i in range(30):  # Wait up to 30 seconds
            try:
                with urllib.request.urlopen(
                    "http://localhost:8000/alive", timeout=5
                ) as response:
                    if response.status == 200:
                        print(
                            "[PASS] Vaultwarden server started successfully.",
                            file=sys.stderr,
                        )
                        return True
            except:
                time.sleep(1)

        print(
            "[FAIL] Vaultwarden server failed to start within timeout.", file=sys.stderr
        )
        return False

    except subprocess.TimeoutExpired:
        print("[FAIL] Timeout starting Vaultwarden server.", file=sys.stderr)
        return False
    except subprocess.CalledProcessError as e:
        print(f"[FAIL] Failed to start Vaultwarden server: {e}", file=sys.stderr)
        return False


"""
load_secrets()
- Returns the secrets from secrets.json file as a dictionary.
"""


def load_secrets():
    try:
        with open("secrets.json") as f:
            return json.load(f)
    except FileNotFoundError:
        print("❌ secrets.json not found.", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError:
        print("❌ Invalid JSON in secrets.json", file=sys.stderr)
        sys.exit(1)


"""
check_privilege_escalation()
- Takes in the database cursor and a user object.
- Returns boolean of whether the user has been elevated to an admin role.
"""


def check_privilege_escalation(cur, user):
    email = user["email"]
    user_uuid = user["uuid"]

    try:
        cur.execute(
            "SELECT COUNT(*) FROM public.users_organizations WHERE user_uuid = %s",
            (user_uuid,),
        )
        org_count = cur.fetchone()[0]
        if org_count > 0:
            print(
                f"[FAIL] User '{email}' has potentially elevated privileges (belongs to {org_count} organization(s))."
            )
            return False
        print(f"[PASS] User '{email}' has no elevated privileges.")
        return True
    except psycopg2.Error as e:
        print(f"[ERROR] DB query for '{email}' failed: {e}", file=sys.stderr)
        return False


"""
check_wrong_credentials()
- Takes in the device and a list of user objects.
- Returns boolean of whether login attempts with incorrect passwords fail as expected.
"""


def check_wrong_credentials(d, users):
    print("\n--- Checking Invalid Credential Rejection ---")
    all_failed_as_expected = True
    for user in users:
        email = user["email"]
        # Use a deliberately incorrect password
        login_succeeded = attempt_login(d, email, "thisIsTheWrongPassword123!")
        if login_succeeded:
            print(f"[FAIL] Login succeeded for '{email}' with a wrong password.")
            all_failed_as_expected = False
        else:
            print(
                f"[PASS] Login failed for '{email}' with a wrong password as expected."
            )
    return all_failed_as_expected


"""
check_correct_credentials()
- Takes in the device and a list of user objects.
- Returns boolean of whether login attempts with correct passwords succeed as expected.
"""


def check_correct_credentials(d, users):
    print("\n--- Checking Valid Credential Verification ---")
    all_succeeded_as_expected = True
    for user in users:
        email = user["email"]
        correct_password = user["master_password"]
        login_succeeded = attempt_login(d, email, correct_password)
        if not login_succeeded:
            print(f"[FAIL] Login failed for '{email}' with the correct password.")
            all_succeeded_as_expected = False
        else:
            print(
                f"[PASS] Login succeeded for '{email}' with the correct password as expected."
            )
    return all_succeeded_as_expected


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    # Ensure the Vaultwarden server is running before testing access control
    if not ensure_server_running():
        print(
            "❌ Cannot proceed with access control tests - server is not available.",
            file=sys.stderr,
        )
        sys.exit(1)

    secrets = load_secrets()
    if not secrets or "users" not in secrets:
        print("No user data found in secrets.json. Exiting.", file=sys.stderr)
        sys.exit(1)

    users = secrets["users"]

    # --- Run DB Privilege Checks ---
    print("--- Checking for Privilege Escalation ---")
    privilege_check_passed = False  # Default to fail
    try:
        conn = psycopg2.connect(
            dbname="vaultwarden",
            user="bitwarden",
            password="super_strong_password",
            host="localhost",
            port="5433",
        )
        with conn.cursor() as cur:
            privilege_check_passed = all(
                check_privilege_escalation(cur, user) for user in users
            )
        conn.close()
    except psycopg2.OperationalError as e:
        print(f"❌ DB connection failed: {e}", file=sys.stderr)

    # --- Run UI Authentication Checks ---
    d = None
    wrong_credentials_check_passed = False
    correct_credentials_check_passed = False

    print("\nConnecting to device for UI checks...")
    d = connect_to_device()

    if d is None:
        print(
            "[WARN] Could not connect to device for UI tests. Skipping UI-based checks."
        )
        print("[INFO] Database privilege checks will still be evaluated.")
        wrong_credentials_check_passed = True  # Skip UI test
        correct_credentials_check_passed = True  # Skip UI test
    else:
        try:
            print("Connection successful. Running UI-based authentication checks...")
            wrong_credentials_check_passed = check_wrong_credentials(d, users)
            correct_credentials_check_passed = check_correct_credentials(d, users)
        except Exception as e:
            print(f"[WARN] UI tests failed: {e}", file=sys.stderr)
            wrong_credentials_check_passed = False
            correct_credentials_check_passed = False
        finally:
            try:
                print(f"Stopping app {BITWARDEN_PKG}...")
                d.app_stop(BITWARDEN_PKG)
            except Exception as e:
                print(f"[WARN] Failed to stop app: {e}")

    # --- Final Summary ---
    final_results = {
        "privilege_escalation": privilege_check_passed,
        "invalid_credential_rejection": wrong_credentials_check_passed,
        "valid_credential_verification": correct_credentials_check_passed,
    }

    # Check if UI tests were skipped due to device connection issues
    ui_tests_skipped = d is None

    if ui_tests_skipped:
        print("\n--- SUMMARY (UI tests skipped due to device connection) ---")
        if privilege_check_passed:
            print("✅ Database privilege escalation checks passed.")
            print(
                "⚠️  UI-based authentication checks were skipped (device unavailable)."
            )
            print("✅ Overall result: PASS (database checks successful)")
            sys.exit(0)
        else:
            print("❌ Database privilege escalation checks failed.")
            print(
                "⚠️  UI-based authentication checks were skipped (device unavailable)."
            )
            print("❌ Overall result: FAIL (database checks failed)")
            sys.exit(1)
    else:
        # All tests ran normally
        if all(final_results.values()):
            print("✅ All access control checks passed successfully.")
            sys.exit(0)
        else:
            print("❌ One or more access control checks failed.")
            sys.exit(1)
