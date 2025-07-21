import psycopg2
import sys
import subprocess
import json

with open("secrets.json") as f:
    secrets = json.load(f)


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


def run_command(cmd):
    result = subprocess.run(cmd, shell=True)
    return result.returncode


def check_wrong_credentials():
    commands = [
        "python synch_app.py --username usera@localhost --password userAPW",
        "python synch_app.py --username userb@localhost --password userBPW123",
        "python synch_app.py --username userb@localhost --password adminPW123"
    ]
    results = [run_command(cmd) for cmd in commands]
    return_val = all(code != 0 for code in results)

    if return_val:
        print(f"[PASS] All attempts to synch with wrong credentials failed.")
    else:
        print(f"[FAIL] Synching with wrong credential(s) suceeded.")
    return return_val


def check_correct_credentials():
    commands = [
        f"python synch_app.py --username userb@localhost --password {secrets['userb_password']}",
        f"python synch_app.py --username admin@localhost --password {secrets['admin_password']}",
        "python synch_app.py --username usera@localhost --password userAPW123"
    ]
    results = [run_command(cmd) for cmd in commands]
    return_val = all(code == 0 for code in results)

    if return_val:
        print(f"[PASS] All attempts to synch with correct credentials succeeded.")
    else:
        print(f"[FAIL] Synching with correct credentials failed.")
    return return_val


if __name__ == "__main__":
    checks = [
            check_user_a(dbname="mydatabase", user="postgres", password="postgresPW", port=5432),
            check_wrong_credentials(),
            check_correct_credentials()
        ]

    if not all(checks):
        print("\nSome tests failed.")
        sys.exit(1)
    else:
        print("\nAll tests passed successfully.")
        sys.exit(0)