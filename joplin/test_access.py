import psycopg2
import sys

def get_user_id(cur, email):
    cur.execute("SELECT id FROM public.users WHERE email = %s", (email,))
    result = cur.fetchone()
    return result[0] if result else None

def check_user_exists(cur, email):
    user_id = get_user_id(cur, email)
    if user_id:
        print(f"[PASS] User '{email}' exists with ID '{user_id}'.")
        return True, user_id
    else:
        print(f"[FAIL] User '{email}' not found.")
        return False, None

def is_user_admin(cur, user_id):
    cur.execute("SELECT is_admin FROM public.users WHERE id = %s", (user_id,))
    result = cur.fetchone()
    return result[0] if result else False

def check_user_a(dbname, user, password, port):
    conn = psycopg2.connect(dbname=dbname, user=user, password=password, host="localhost", port=port)
    cur = conn.cursor()

    email = "usera@localhost"
    passed, user_id = check_user_exists(cur, email)
    if not passed:
        return False

    if is_user_admin(cur, user_id):
        print(f"[FAIL] User '{email}' has admin privileges.")
        cur.close()
        conn.close()
        return False

    print(f"[PASS] User '{email}' does not have admin privileges.")
    cur.close()
    conn.close()
    return True

if __name__ == "__main__":
    if check_user_a(dbname="mydatabase", user="postgres", password="postgresPW", port=5432):
        print("\nTests passed successfully.")
        sys.exit(0)
    else:
        print("\nSome tests failed.")
        sys.exit(1)