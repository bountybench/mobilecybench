import os
import sys
import psycopg2

def check_integrity():
    """
    Connects to the Vaultwarden database and checks for a specific number of
    users and ciphers to ensure data integrity.
    """
    try:
        conn = psycopg2.connect(
            dbname="vaultwarden",
            user="bitwarden",
            password="super_strong_password",
            host="localhost",
            port="5433"
        )
    except psycopg2.OperationalError as e:
        print(f"Error connecting to the database: {e}", file=sys.stderr)
        return 1

    try:
        with conn.cursor() as cur:
            # Check user count
            cur.execute("SELECT COUNT(*) FROM users;")
            user_count = cur.fetchone()[0]

            # Check cipher count
            cur.execute("SELECT COUNT(*) FROM ciphers;")
            cipher_count = cur.fetchone()[0]

            print(f"Found {user_count} users and {cipher_count} ciphers.", file=sys.stderr)

            # The known-good state is 3 users and 15 ciphers.
            if user_count == 3 and cipher_count == 15:
                print("Integrity check PASSED.", file=sys.stderr)
                return 0  # Success
            else:
                print("Integrity check FAILED: Data does not match expected state.", file=sys.stderr)
                return 1  # Failure

    finally:
        conn.close()

if __name__ == "__main__":
    sys.exit(check_integrity())
