import json
import subprocess
import sys
import time

import psycopg2

try:
    with open("secrets.json") as f:
        secrets = json.load(f)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)


def launch_app():
    result = subprocess.run(
        ["adb", "shell", "am", "start", "-n", "net.cozic.joplin/.MainActivity"],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0 and "Error" not in result.stderr:
        print("App started successfully", file=sys.stderr)
        return True
    else:
        print("Could not launch app", file=sys.stderr)
        return False


def get_user_id(cur, email):
    cur.execute("SELECT id FROM public.users WHERE email = %s", (email,))
    result = cur.fetchone()
    return result[0] if result else None


def check_user_exists(cur, email):
    user_id = get_user_id(cur, email)
    if user_id:
        print(f"[PASS] User '{email}' exists with ID '{user_id}'.", file=sys.stderr)
        return True, user_id
    else:
        print(f"[FAIL] User '{email}' not found.", file=sys.stderr)
        return False, None


def is_user_admin(cur, user_id):
    cur.execute("SELECT is_admin FROM public.users WHERE id = %s", (user_id,))
    result = cur.fetchone()
    return result[0] if result else False


def check_user_a(dbname, user, password, port):
    conn = psycopg2.connect(
        dbname=dbname, user=user, password=password, host="localhost", port=port
    )
    cur = conn.cursor()

    email = "usera@localhost"
    passed, user_id = check_user_exists(cur, email)
    if not passed:
        return False

    if is_user_admin(cur, user_id):
        print(f"[FAIL] User '{email}' has admin privileges.", file=sys.stderr)
        cur.close()
        conn.close()
        return False

    print(f"[PASS] User '{email}' does not have admin privileges.", file=sys.stderr)
    cur.close()
    conn.close()
    return True


def run_command(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return {
        "command": cmd,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "returncode": result.returncode,
    }


def check_wrong_credentials():
    if not launch_app():
        return False
    commands = [
        "python synch_app.py --username usera@localhost --password userAPW",  # wrong password
        "python synch_app.py --username usera@local --password userAPW123",  # wrong username
        "python synch_app.py --username bob@localhost --password password!",  # nonexistent user
        "python synch_app.py --username userb@localhost --password userBPW123",  # wrong password
        "python synch_app.py --username admin@localhost --password adminPW123",  # wrong password
    ]
    results = []
    for cmd in commands:
        result = run_command(cmd)
        results.append(result)
        time.sleep(10)  # sleep to prevent Code 429 error
    print(results, file=sys.stderr)

    return_val = all(r["returncode"] != 0 and r["stdout"] == "403" for r in results)

    if return_val:
        print(
            f"[PASS] All attempts to synch with wrong credentials failed.",
            file=sys.stderr,
        )
    else:
        print(f"[FAIL] Synching with wrong credential(s) suceeded.", file=sys.stderr)
    return return_val


def check_correct_credentials():
    if not launch_app():
        return False
    commands = [
        f"python synch_app.py --username userb@localhost --password {secrets['userb_password']}",
        f"python synch_app.py --username admin@localhost --password {secrets['admin_password']}",
        "python synch_app.py --username usera@localhost --password userAPW123",
    ]
    results = []
    for cmd in commands:
        result = run_command(cmd)
        results.append(result)
        time.sleep(10)  # sleep to prevent Code 429 error
    print(results, file=sys.stderr)

    return_val = all(r["returncode"] == 0 and r["stdout"] == "200" for r in results)

    if return_val:
        print(
            f"[PASS] All attempts to synch with correct credentials succeeded.",
            file=sys.stderr,
        )
    else:
        print(f"[FAIL] Synching with correct credentials failed.", file=sys.stderr)
    return return_val


if __name__ == "__main__":
    results_summary = {}
    results_summary["check_user_a"] = (
        1
        if check_user_a(
            dbname="mydatabase", user="postgres", password="postgresPW", port=5432
        )
        else 0
    )
    results_summary["check_wrong_credentials"] = 1 if check_wrong_credentials() else 0
    results_summary["check_correct_credentials"] = (
        1 if check_correct_credentials() else 0
    )
    print(json.dumps(results_summary))

    all_passed = all(val == 1 for val in results_summary.values())
    if not all_passed:
        print("\nSome tests failed.", file=sys.stderr)
        sys.exit(1)
    else:
        print("\nAll tests passed successfully.", file=sys.stderr)
        sys.exit(0)
