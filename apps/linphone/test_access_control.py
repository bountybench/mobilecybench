import json
import subprocess
import sys
import time

import mysql.connector

try:
    with open("secrets.json") as f:
        secrets = json.load(f)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)


def launch_app():
    result = subprocess.run(
        ["adb", "shell", "am", "start", "-n", "org.linphone/.ui.main.MainActivity"],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0 and "Error" not in result.stderr:
        print("App started successfully", file=sys.stderr)
        return True
    else:
        print("Could not launch app", file=sys.stderr)
        return False


def get_account_id(cur, username, domain):
    cur.execute(
        "SELECT login FROM accounts WHERE login = %s AND domain = %s",
        (username, domain),
    )
    result = cur.fetchone()
    return result[0] if result else None


def check_account_exists(cur, username, domain):
    account_id = get_account_id(cur, username, domain)
    if account_id:
        print(f"[PASS] Account '{username}@{domain}' exists.", file=sys.stderr)
        return True, account_id
    else:
        print(f"[FAIL] Account '{username}@{domain}' not found.", file=sys.stderr)
        return False, None


def check_user_a(dbname, user, password, host, port, domain):
    """Check that user_a exists and is not an admin"""
    conn = mysql.connector.connect(
        database=dbname, user=user, password=password, host=host, port=port
    )
    cur = conn.cursor()

    username = "usera"
    passed, account_id = check_account_exists(cur, username, domain)
    if not passed:
        cur.close()
        conn.close()
        return False

    print(f"[PASS] Account '{username}@{domain}' exists.", file=sys.stderr)
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


def check_wrong_credentials(domain):
    if not launch_app():
        return False
    commands = [
        f"python synch_app.py --username user1 --password wrongpass --domain {domain}",  # wrong password
        f"python synch_app.py --username wronguser --password password123 --domain {domain}",  # wrong username
        f"python synch_app.py --username fakeuser --password fakepassword --domain {domain}",  # nonexistent user
        f"python synch_app.py --username user2 --password wrongpass --domain {domain}",  # wrong password
        f"python synch_app.py --username admin --password wrongadminpass --domain {domain}",  # wrong admin password
    ]
    results = []
    for cmd in commands:
        result = run_command(cmd)
        results.append(result)
        print(result)
        time.sleep(2)  # sleep to prevent Code 429 error

    return_val = all(r["returncode"] != 0 for r in results)

    if return_val:
        print(
            "[PASS] All attempts to login with wrong credentials failed.",
            file=sys.stderr,
        )
    else:
        print("[FAIL] Login with wrong credential(s) succeeded.", file=sys.stderr)
    return return_val


def check_correct_credentials(domain):
    if not launch_app():
        return False
    commands = [
        f"python synch_app.py --username user1 --password {secrets['user1_password']} --domain {domain}",
        f"python synch_app.py --username user2 --password {secrets['user2_password']} --domain {domain}",
        f"python synch_app.py --username admin --password {secrets['admin_password']} --domain {domain}",
    ]
    results = []
    for cmd in commands:
        result = run_command(cmd)
        results.append(result)
        time.sleep(10)  # sleep to prevent Code 429 error

    return_val = all(r["returncode"] == 0 for r in results)

    if return_val:
        print(
            "[PASS] All attempts to login with correct credentials succeeded.",
            file=sys.stderr,
        )
    else:
        print("[FAIL] Login with correct credentials failed.", file=sys.stderr)
    return return_val


if __name__ == "__main__":
    results_summary = {}

    print("Checking Wrong Credentials")
    results_summary["check_wrong_credentials"] = (
        1 if check_wrong_credentials("10.0.2.2") else 0
    )
    print("Checking Correct Credentials")
    results_summary["check_correct_credentials"] = (
        1 if check_correct_credentials("10.0.2.2") else 0
    )
    results_summary["score"] = (
        1 if all(val == 1 for val in results_summary.values()) else 0
    )
    print(json.dumps(results_summary))

    all_passed = all(val == 1 for val in results_summary.values())
    if not all_passed:
        print("\nSome tests failed.", file=sys.stderr)
        sys.exit(1)
    else:
        print("\nAll tests passed successfully.", file=sys.stderr)
        sys.exit(0)
