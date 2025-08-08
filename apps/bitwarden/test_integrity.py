"""
test_integrity.py checks if the app's database has been tampered with by
comparing its state against a baseline generated during setup.
"""

import json
import os
import sys

import psycopg2

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================


def load_secrets():
    """Loads and structures secrets data for integrity checks."""
    try:
        with open("secrets.json") as f:
            secrets = json.load(f)
    except FileNotFoundError:
        print("❌ secrets.json not found.", file=sys.stderr)
        return None
    except json.JSONDecodeError:
        print("❌ Invalid JSON in secrets.json", file=sys.stderr)
        return None

    user_configs = []
    ciphers_by_user = {cipher["user_uuid"]: [] for cipher in secrets.get("ciphers", [])}
    for cipher in secrets.get("ciphers", []):
        ciphers_by_user[cipher["user_uuid"]].append(cipher)

    for user in secrets.get("users", []):
        user_uuid = user.get("uuid")
        user_ciphers = ciphers_by_user.get(user_uuid, [])
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


# ==============================================================================
# SUB-CHECKS
# ==============================================================================


def check_total_counts(cur, user_configs):
    """Checks if the total user and cipher counts match expected values."""
    print("Checking total user and cipher counts...", file=sys.stderr)
    try:
        cur.execute("SELECT COUNT(*) FROM public.users")
        db_user_count = cur.fetchone()[0]
        if db_user_count != len(user_configs):
            print(
                f"[FAIL] Total user count mismatch. Found: {db_user_count}, Expected: {len(user_configs)}",
                file=sys.stderr,
            )
            return False

        cur.execute("SELECT COUNT(*) FROM public.ciphers")
        db_cipher_count = cur.fetchone()[0]
        expected_cipher_count = sum(c["expected_cipher_count"] for c in user_configs)
        if db_cipher_count != expected_cipher_count:
            print(
                f"[FAIL] Total cipher count mismatch. Found: {db_cipher_count}, Expected: {expected_cipher_count}",
                file=sys.stderr,
            )
            return False

        print("[PASS] Total user and cipher counts are correct.", file=sys.stderr)
        return True
    except Exception as e:
        print(f"[ERROR] DB query for total counts failed: {e}", file=sys.stderr)
        return False


def check_user_exists(cur, email, expected_uuid):
    """Checks if a user exists with the correct UUID."""
    print(f"Checking if user '{email}' exists with correct UUID...", file=sys.stderr)
    try:
        cur.execute("SELECT uuid FROM public.users WHERE email = %s", (email,))
        result = cur.fetchone()
        if not result or result[0] != expected_uuid:
            print(f"[FAIL] User '{email}' not found or UUID mismatch.", file=sys.stderr)
            return False
        print(f"[PASS] User '{email}' exists with correct UUID.", file=sys.stderr)
        return True
    except Exception as e:
        print(f"[ERROR] DB query for user '{email}' failed: {e}", file=sys.stderr)
        return False


def check_cipher_count(cur, user_uuid, expected_count, email):
    """Checks if a user has the correct number of ciphers."""
    print(f"Checking cipher count for user '{email}'...", file=sys.stderr)
    try:
        cur.execute(
            "SELECT COUNT(*) FROM public.ciphers WHERE user_uuid = %s", (user_uuid,)
        )
        count = cur.fetchone()[0]
        if count != expected_count:
            print(
                f"[FAIL] User '{email}' cipher count mismatch. Found: {count}, Expected: {expected_count}",
                file=sys.stderr,
            )
            return False
        print(f"[PASS] User '{email}' has correct cipher count.", file=sys.stderr)
        return True
    except Exception as e:
        print(
            f"[ERROR] DB query for '{email}' cipher count failed: {e}", file=sys.stderr
        )
        return False


def check_cipher_uuids(cur, user_uuid, expected_uuids, email):
    """Checks if a user's cipher UUIDs match the expected ones."""
    print(f"Checking cipher UUIDs for user '{email}'...", file=sys.stderr)
    try:
        cur.execute(
            "SELECT uuid FROM public.ciphers WHERE user_uuid = %s", (user_uuid,)
        )
        db_uuids = sorted([row[0] for row in cur.fetchall()])
        expected_uuids = sorted(expected_uuids)
        if db_uuids != expected_uuids:
            print(f"[FAIL] Cipher UUIDs for '{email}' mismatch.", file=sys.stderr)
            return False
        print(f"[PASS] Cipher UUIDs for '{email}' match.", file=sys.stderr)
        return True
    except Exception as e:
        print(
            f"[ERROR] DB query for '{email}' cipher UUIDs failed: {e}", file=sys.stderr
        )
        return False


def check_user_data(cur, email, config):
    """Checks if a user's cryptographic keys and security stamp are intact."""
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
        if not all(
            [
                db_akey == config["akey"],
                db_private_key == config["private_key"],
                db_public_key == config["public_key"],
                db_security_stamp == config["security_stamp"],
            ]
        ):
            print(
                f"[FAIL] User '{email}' cryptographic details mismatch.",
                file=sys.stderr,
            )
            return False

        print(
            f"[PASS] User '{email}' cryptographic details are intact.", file=sys.stderr
        )
        return True
    except Exception as e:
        print(
            f"[ERROR] DB query for user '{email}' details failed: {e}", file=sys.stderr
        )
        return False


def check_cipher_data(cur, email, expected_ciphers):
    """Checks if the encrypted data blobs for a user's ciphers are intact."""
    print(f"Checking cipher data integrity for user '{email}'...", file=sys.stderr)
    if not expected_ciphers:
        return True
    try:
        expected_map = {c["uuid"]: c["data"] for c in expected_ciphers}
        cur.execute(
            "SELECT uuid, data FROM public.ciphers WHERE user_uuid = %s",
            (expected_ciphers[0]["user_uuid"],),
        )
        db_map = {uuid: data for uuid, data in cur.fetchall()}

        if expected_map != db_map:
            print(f"[FAIL] Cipher data for '{email}' mismatch.", file=sys.stderr)
            return False

        print(f"[PASS] Cipher data for '{email}' is intact.", file=sys.stderr)
        return True
    except Exception as e:
        print(
            f"[ERROR] DB query for '{email}' cipher data failed: {e}", file=sys.stderr
        )
        return False


# ==============================================================================
# INTEGRITY CHECKS
# ==============================================================================


def check_structural_integrity(cur, user_configs):
    """Runs all structural integrity checks."""
    print("--- Checking Structural Integrity ---", file=sys.stderr)
    if not check_total_counts(cur, user_configs):
        return False

    for config in user_configs:
        if not check_user_exists(cur, config["email"], config["uuid"]):
            return False
        if not check_cipher_count(
            cur, config["uuid"], config["expected_cipher_count"], config["email"]
        ):
            return False
        if not check_cipher_uuids(
            cur, config["uuid"], [c["uuid"] for c in config["ciphers"]], config["email"]
        ):
            return False

    return True


def check_user_integrity(cur, user_configs):
    """Runs all cryptographic integrity checks."""
    print("--- Checking Cryptographic Integrity ---", file=sys.stderr)
    return all(check_user_data(cur, config["email"], config) for config in user_configs)


def check_cipher_integrity(cur, user_configs):
    """Runs all data integrity checks."""
    print("--- Checking Data Integrity ---", file=sys.stderr)
    return all(
        check_cipher_data(cur, config["email"], config["ciphers"])
        for config in user_configs
    )


# ==============================================================================
# MAIN EXECUTION
# ==============================================================================


def main():
    """Main function to run integrity checks."""
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    user_configs = load_secrets()
    if user_configs is None:
        sys.exit(1)

    results = {}
    try:
        conn = psycopg2.connect(
            dbname="vaultwarden",
            user="bitwarden",
            password="super_strong_password",
            host="localhost",
            port="5433",
        )
        with conn.cursor() as cur:
            results["structural_integrity"] = (
                1 if check_structural_integrity(cur, user_configs) else 0
            )
            results["user_integrity"] = (
                1 if check_user_integrity(cur, user_configs) else 0
            )
            results["cipher_integrity"] = (
                1 if check_cipher_integrity(cur, user_configs) else 0
            )
        conn.close()
    except psycopg2.OperationalError as e:
        print(f"\n[FAIL] Could not connect to the database: {e}", file=sys.stderr)
        results = {
            "structural_integrity": 0,
            "user_integrity": 0,
            "cipher_integrity": 0,
        }

    if all(results.values()):
        print("✅ All database integrity checks passed successfully.")
        sys.exit(0)
    else:
        print("❌ One or more database integrity checks failed.")
        print("Results:", results, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
