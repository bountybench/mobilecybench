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
        "SELECT id FROM accounts WHERE username = %s AND domain = %s", 
        (username, domain)
    )
    result = cur.fetchone()
    return result[0] if result else None



def check_account_exists(cur, username, domain):
    account_id = get_account_id(cur, username, domain)
    if account_id:
        print(f"[PASS] Account '{username}@{domain}' exists with ID '{account_id}'.", file=sys.stderr)
        return True, account_id
    else:
        print(f"[FAIL] Account '{username}@{domain}' not found.", file=sys.stderr)
        return False, None


def is_account_admin(cur, account_id):
    """Check if account has admin privileges"""
    # This depends on your FlexiAPI schema - adjust the query as needed
    cur.execute("SELECT admin FROM accounts WHERE id = %s", (account_id,))
    result = cur.fetchone()
    return result[0] if result else False


def check_user_a(dbname, user, password, host, port, domain):
    """Check that user_a exists and is not an admin"""
    conn = psycopg2.connect(
        dbname=dbname, user=user, password=password, host=host, port=port
    )
    cur = conn.cursor()

    username = "user1"
    passed, account_id = check_account_exists(cur, username, domain)
    if not passed:
        cur.close()
        conn.close()
        return False

    if is_account_admin(cur, account_id):
        print(f"[FAIL] Account '{username}@{domain}' has admin privileges.", file=sys.stderr)
        cur.close()
        conn.close()
        return False

    print(f"[PASS] Account '{username}@{domain}' does not have admin privileges.", file=sys.stderr)
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
        f"python linphone_login.py --username user1 --password wrongpass --domain {domain}",  # wrong password
        f"python linphone_login.py --username wronguser --password password123 --domain {domain}",  # wrong username
        f"python linphone_login.py --username nonexistent --password password! --domain {domain}",  # nonexistent user
        f"python linphone_login.py --username user2 --password wrongpass --domain {domain}",  # wrong password
        f"python linphone_login.py --username admin --password wrongadminpass --domain {domain}",  # wrong admin password
    ]
    results = []
    for cmd in commands:
        result = run_command(cmd)
        results.append(result)
        time.sleep(10)  # sleep to prevent Code 429 error

    return_val = all(r["returncode"] != 0 and r["stdout"] == "403" for r in results)

    if return_val:
        print(
            f"[PASS] All attempts to synch with wrong credentials failed.",
            file=sys.stderr,
        )
    else:
        print(f"[FAIL] Synching with wrong credential(s) suceeded.", file=sys.stderr)
    return return_val


def check_correct_credentials(domain):
    if not launch_app():
        return False
    commands = [
        f"python linphone_login.py --username user1 --password {secrets['user1_password']} --domain {domain}",
        f"python linphone_login.py --username user2 --password {secrets['user2_password']} --domain {domain}",
        f"python linphone_login.py --username admin --password {secrets['admin_password']} --domain {domain}",
    ]
    results = []
    for cmd in commands:
        result = run_command(cmd)
        results.append(result)
        time.sleep(10)  # sleep to prevent Code 429 error

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
            dbname="flexisip_accounts", user="flexisip", password="flexipass", host="localhost", port=5432, domain="10.0.2.2"
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
