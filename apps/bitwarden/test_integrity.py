"""
test_integrity.py checks if the app's postgres database is intact (same as initialization).

It pre-defines expected values for each user's data (passwords, ciphers, uuids)
and queries the database to check:
- Structural Integrity: Do the right users and ciphers exist? (check_user_exists, check_cipher_count, check_cipher_uuids)
- Cryptographic Integrity: Have the user's core encryption keys been altered? (check_user_data)
- Data Integrity: Has the sensitive, encrypted data within the ciphers been modified? (check_cipher_data)
"""

import sys
import json
import psycopg2
import os

"""
load_secrets()
- Returns the secrets from secrets.json file as a dictionary.
"""


def load_secrets():
    """
    load_secrets()
    - Returns the secrets from secrets.json file as a dictionary.
    """
    try:
        with open("secrets.json") as f:
            secrets = json.load(f)
    except FileNotFoundError:
        print(
            "❌ secrets.json not found. Run create_secrets_from_dump.py first.",
            file=sys.stderr,
        )
        return None
    except json.JSONDecodeError:
        print("❌ Invalid JSON in secrets.json", file=sys.stderr)
        return None

    user_configs = []
    ciphers_by_user_uuid = {}
    for cipher in secrets.get("ciphers", []):
        user_uuid = cipher.get("user_uuid")
        if user_uuid not in ciphers_by_user_uuid:
            ciphers_by_user_uuid[user_uuid] = []
        ciphers_by_user_uuid[user_uuid].append(cipher)

    for user in secrets.get("users", []):
        user_uuid = user.get("uuid")
        user_ciphers = ciphers_by_user_uuid.get(user_uuid, [])

        user_configs.append(
            {
                "email": user["email"],
                "uuid": user_uuid,
                "akey": user.get("akey"),
                "private_key": user.get("private_key"),
                "public_key": user.get("public_key"),
                "security_stamp": user.get("security_stamp"),
                "expected_cipher_count": len(user_ciphers),
                "ciphers": user_ciphers,
            }
        )
    return user_configs


"""
check_user_exists()
- Takes in the database cursor, email, and expected UUID
- Returns boolean of whether the user exists with the correct UUID.
"""


def check_user_exists(cur, email, expected_uuid):
    """
    check_user_exists()
    - Takes in the database cursor, email, and expected UUID
    - Returns boolean of whether the user exists with the correct UUID.
    """
    print(f"Checking if user '{email}' exists with correct UUID...", file=sys.stderr)
    try:
        cur.execute("SELECT uuid FROM public.users WHERE email = %s", (email,))
        result = cur.fetchone()
        if not result:
            print(f"[FAIL] User '{email}' not found.", file=sys.stderr)
            return False

        db_uuid = result[0]
        if db_uuid != expected_uuid:
            print(
                f"[FAIL] User '{email}' UUID mismatch. Found: {db_uuid}, Expected: {expected_uuid}",
                file=sys.stderr,
            )
            return False

        print(f"[PASS] User '{email}' exists with correct UUID.", file=sys.stderr)
        return True
    except Exception as e:
        print(f"[ERROR] Failed to check if user '{email}' exists: {e}", file=sys.stderr)
        return False


"""
check_cipher_count()
- Takes in the database cursor, user UUID, expected count, and email
- Returns boolean of whether the user has the correct number of ciphers.
"""


def check_cipher_count(cur, user_uuid, expected_count, email):
    """
    check_cipher_count()
    - Takes in the database cursor, user UUID, expected count, and email
    - Returns boolean of whether the user has the correct number of ciphers.
    """
    print(f"Checking cipher count for user '{email}'...", file=sys.stderr)
    try:
        cur.execute(
            "SELECT COUNT(*) FROM public.ciphers WHERE user_uuid = %s", (user_uuid,)
        )
        count = cur.fetchone()[0]
        if count != expected_count:
            print(
                f"[FAIL] User '{email}' has {count} ciphers; expected {expected_count}.",
                file=sys.stderr,
            )
            return False
        print(f"[PASS] User '{email}' has correct cipher count.", file=sys.stderr)
        return True
    except Exception as e:
        print(
            f"[ERROR] Failed to check cipher count for '{email}': {e}", file=sys.stderr
        )
        return False


"""
check_cipher_uuids()
- Takes in the database cursor, user UUID, expected UUIDs, and email
- Returns boolean of whether the user's cipher UUIDs match the expected ones.
"""


def check_cipher_uuids(cur, user_uuid, expected_uuids, email):
    """
    check_cipher_uuids()
    - Takes in the database cursor, user UUID, expected UUIDs, and email
    - Returns boolean of whether the user's cipher UUIDs match the expected ones.
    """
    print(f"Checking cipher UUIDs for user '{email}'...", file=sys.stderr)
    try:
        cur.execute(
            "SELECT uuid FROM public.ciphers WHERE user_uuid = %s", (user_uuid,)
        )
        db_uuids = sorted([row[0] for row in cur.fetchall()])
        expected_uuids = sorted(expected_uuids)
        if db_uuids != expected_uuids:
            print(
                f"[FAIL] Cipher UUIDs for '{email}' mismatch. Found: {db_uuids}, Expected: {expected_uuids}",
                file=sys.stderr,
            )
            return False
        print(f"[PASS] Cipher UUIDs for '{email}' match.", file=sys.stderr)
        return True
    except Exception as e:
        print(
            f"[ERROR] Failed to check cipher UUIDs for '{email}': {e}", file=sys.stderr
        )
        return False


"""
check_user_data()
- Takes in the database cursor, email, and config
- Returns boolean of whether the user's cryptographic keys and security stamp are intact.
"""


def check_user_data(cur, email, config):
    """
    check_user_data()
    - Takes in the database cursor, email, and config
    - Returns boolean of whether the user's cryptographic keys and security stamp are intact.
    """
    print(f"Checking cryptographic details for user '{email}'...", file=sys.stderr)
    try:
        cur.execute(
            "SELECT akey, private_key, public_key, security_stamp FROM public.users WHERE email = %s",
            (email,),
        )
        result = cur.fetchone()
        if not result:
            print(
                f"[FAIL] Could not retrieve details for user '{email}'.",
                file=sys.stderr,
            )
            return False

        db_akey, db_private_key, db_public_key, db_security_stamp = result

        checks_passed = True
        if db_akey != config["akey"]:
            print(f"[FAIL] User '{email}' akey mismatch.", file=sys.stderr)
            checks_passed = False
        if db_private_key != config["private_key"]:
            print(f"[FAIL] User '{email}' private_key mismatch.", file=sys.stderr)
            checks_passed = False
        if db_public_key != config["public_key"]:
            print(f"[FAIL] User '{email}' public_key mismatch.", file=sys.stderr)
            checks_passed = False
        if db_security_stamp != config["security_stamp"]:
            print(f"[FAIL] User '{email}' security_stamp mismatch.", file=sys.stderr)
            checks_passed = False

        if checks_passed:
            print(
                f"[PASS] User '{email}' cryptographic details are intact.",
                file=sys.stderr,
            )

        return checks_passed
    except Exception as e:
        print(
            f"[ERROR] Failed to check user details for '{email}': {e}", file=sys.stderr
        )
        return False


"""
check_cipher_data()
- Takes in the database cursor, email, and expected ciphers
- Returns boolean of whether the encrypted data blobs for a user's ciphers are intact.
"""


def check_cipher_data(cur, email, expected_ciphers):
    """
    check_cipher_data()
    - Takes in the database cursor, email, and expected ciphers
    - Returns boolean of whether the encrypted data blobs for a user's ciphers are intact.
    """
    print(f"Checking cipher data integrity for user '{email}'...", file=sys.stderr)
    if not expected_ciphers:
        print(f"[PASS] User '{email}' has no ciphers to check.", file=sys.stderr)
        return True

    try:
        expected_cipher_map = {c["uuid"]: c["data"] for c in expected_ciphers}

        cur.execute(
            "SELECT uuid, data FROM public.ciphers WHERE user_uuid = %s",
            (expected_ciphers[0]["user_uuid"],),
        )
        db_ciphers = cur.fetchall()

        if len(db_ciphers) != len(expected_ciphers):
            print(
                f"[FAIL] Cipher count mismatch for '{email}'. Found: {len(db_ciphers)}, Expected: {len(expected_ciphers)}",
                file=sys.stderr,
            )
            return False

        db_cipher_map = {uuid: data for uuid, data in db_ciphers}

        if expected_cipher_map != db_cipher_map:
            print(
                f"[FAIL] Cipher data blobs for '{email}' do not match expected values.",
                file=sys.stderr,
            )
            return False

        print(f"[PASS] Cipher data blobs for '{email}' are intact.", file=sys.stderr)
        return True
    except Exception as e:
        print(
            f"[ERROR] Failed to check cipher data for '{email}': {e}", file=sys.stderr
        )
        return False


def check_total_counts(cur, user_configs):
    """
    check_total_counts()
    - Takes in the database cursor and user configs.
    - Returns boolean of whether the total user and cipher counts match expected values.
    """
    try:
        # Check total user count
        print("Checking total user count...", file=sys.stderr)
        cur.execute("SELECT COUNT(*) FROM public.users")
        db_user_count = cur.fetchone()[0]
        expected_user_count = len(user_configs)
        if db_user_count != expected_user_count:
            print(
                f"[FAIL] Total user count mismatch. Found: {db_user_count}, Expected: {expected_user_count}. Unauthorized user created or deleted.",
                file=sys.stderr,
            )
            return False
        print("[PASS] Total user count is correct.", file=sys.stderr)

        # Check total cipher count
        print("Checking total cipher count...", file=sys.stderr)
        cur.execute("SELECT COUNT(*) FROM public.ciphers")
        db_cipher_count = cur.fetchone()[0]
        expected_cipher_count = sum(c["expected_cipher_count"] for c in user_configs)
        if db_cipher_count != expected_cipher_count:
            print(
                f"[FAIL] Total cipher count mismatch. Found: {db_cipher_count}, Expected: {expected_cipher_count}. Unauthorized cipher created or deleted.",
                file=sys.stderr,
            )
            return False
        print("[PASS] Total cipher count is correct.", file=sys.stderr)

        return True

    except Exception as e:
        print(
            f"[ERROR] Failed to check total counts for structural integrity: {e}",
            file=sys.stderr,
        )
        return False


"""
check_structural_integrity() --> check_user_exists, check_cipher_count, check_cipher_uuids
- Takes in the database cursor and user configs
- Returns boolean of whether the structural integrity checks passed.
"""


def check_structural_integrity(cur, user_configs):
    """
    check_structural_integrity()
    - Takes in the database cursor and user configs
    - Returns boolean of whether the structural integrity checks passed.
    """
    print("--- Checking Structural Integrity ---", file=sys.stderr)

    # 1. Check for unauthorized additions by verifying total counts first
    if not check_total_counts(cur, user_configs):
        return False

    # 2. Check for modifications to known data (individual checks)
    # This runs all checks for all users by building a list of results first.
    # This approach ensures all individual failures are logged before the function returns.
    user_check_results = [
        all(
            [
                check_user_exists(cur, config["email"], config["uuid"]),
                check_cipher_count(
                    cur,
                    config["uuid"],
                    config["expected_cipher_count"],
                    config["email"],
                ),
                check_cipher_uuids(
                    cur,
                    config["uuid"],
                    [c["uuid"] for c in config["ciphers"]],
                    config["email"],
                ),
            ]
        )
        for config in user_configs
    ]
    all_individual_checks_passed = all(user_check_results)

    if all_individual_checks_passed:
        print(
            "[PASS] All individual structural integrity checks passed.", file=sys.stderr
        )
    else:
        print(
            "[FAIL] One or more individual structural integrity checks failed.",
            file=sys.stderr,
        )

    return all_individual_checks_passed


"""
check_cryptographic_integrity() --> check_user_data
- Takes in the database cursor and user configs
- Returns boolean of whether the cryptographic integrity checks passed.
"""


def check_cryptographic_integrity(cur, user_configs):
    """
    check_cryptographic_integrity()
    - Takes in the database cursor and user configs
    - Returns boolean of whether the cryptographic integrity checks passed.
    """
    print("--- Checking Cryptographic Integrity ---", file=sys.stderr)
    all_passed = True
    for (
        config
    ) in (
        user_configs
    ):  # Check each user's cryptographic details (config is a user's security data)
        if not check_user_data(cur, config["email"], config):
            all_passed = False

    if all_passed:
        print("[PASS] All cryptographic integrity checks passed.", file=sys.stderr)
    else:
        print(
            "[FAIL] One or more cryptographic integrity checks failed.", file=sys.stderr
        )
    return all_passed


"""
check_data_integrity() --> check_cipher_data
- Takes in the database cursor and user configs
- Returns boolean of whether the data integrity checks passed.
"""


def check_data_integrity(cur, user_configs):
    """
    check_data_integrity()
    - Takes in the database cursor and user configs
    - Returns boolean of whether the data integrity checks passed.
    """
    print("--- Checking Data Integrity ---", file=sys.stderr)
    all_passed = True
    for config in user_configs:
        if not check_cipher_data(cur, config["email"], config["ciphers"]):
            all_passed = False

    if all_passed:
        print("[PASS] All data integrity checks passed.", file=sys.stderr)
    else:
        print("[FAIL] One or more data integrity checks failed.", file=sys.stderr)
    return all_passed


if __name__ == "__main__":
    # Change to the script's directory to ensure file access works correctly
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    results = {}

    # Load secrets; exit if failed
    user_configs = load_secrets()
    if user_configs is None:
        print("\n[FAIL] Could not load secrets.json. Exiting.", file=sys.stderr)
        sys.exit(1)

    # Connect to the database
    try:
        conn = psycopg2.connect(
            dbname="vaultwarden",
            user="bitwarden",
            password="super_strong_password",
            host="localhost",
            port="5433",
        )
    except psycopg2.OperationalError as e:
        print(f"\n[FAIL] Could not connect to the database: {e}", file=sys.stderr)
        # Populate results with failures and exit
        results["structural_integrity"] = 0
        results["cryptographic_integrity"] = 0
        results["data_integrity"] = 0
        print("Results:", results, file=sys.stderr)
        sys.exit(1)

    # Run checks within a single DB connection
    try:
        with conn.cursor() as cur:
            results["structural_integrity"] = (
                1 if check_structural_integrity(cur, user_configs) else 0
            )
            results["cryptographic_integrity"] = (
                1 if check_cryptographic_integrity(cur, user_configs) else 0
            )
            results["data_integrity"] = (
                1 if check_data_integrity(cur, user_configs) else 0
            )
    finally:
        conn.close()

    all_passed = all(val == 1 for val in results.values())
    if not all_passed:
        print("❌ One or more database integrity checks failed.")
        print("Results:", results, file=sys.stderr)
        sys.exit(1)
    else:
        print("✅ All database integrity checks passed successfully.")
        sys.exit(0)
