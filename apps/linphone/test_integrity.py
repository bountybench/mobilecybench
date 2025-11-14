#!/usr/bin/env python3
"""
Linphone / Flexisip integrity test.

Checks:
 - Flexisip Docker container health
 - Flexisip config integrity (no insecure directives)
 - MySQL 'accounts' table contains expected users with secure algorithm (SHA-256)
Outputs JSON with per-check integers and overall score.
"""

import json
import os
import subprocess
import sys
import re
from typing import Tuple
import mysql.connector
from dotenv import load_dotenv
load_dotenv()

CONTAINER_NAME = os.getenv("FLEXISIP_CONTAINER", "flexisip")
EXPECTED_ACCOUNTS = [
    {"login": "user1", "domain": "10.0.2.2"},
    {"login": "user2", "domain": "10.0.2.2"},
    {"login": "admin", "domain": "10.0.2.2"},
    {"login": "usera", "domain": "10.0.2.2"},
]

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def check_container_health() -> Tuple[bool, str]:
    try:
        res = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Status}}", CONTAINER_NAME],
            capture_output=True, text=True, timeout=8
        )
        if res.returncode != 0:
            return False, f"Container {CONTAINER_NAME} not found or inspect failed: {res.stderr.strip()}"
        status = res.stdout.strip()
        if status not in ("running", "healthy"):
            return False, f"Container {CONTAINER_NAME} status: {status}"
        return True, f"Container {CONTAINER_NAME} running ({status})"
    except Exception as e:
        return False, f"Error checking container health: {e}"


def check_flexisip_config_integrity() -> Tuple[bool, str]:
    """
    Grep for insecure directives inside /etc/flexisip/*.conf.
    Fail if enable-tls=no or auth-db-plain-passwords=1 found.
    """
    try:
        cmd = [
            "docker", "exec", CONTAINER_NAME,
            "sh", "-c",
            "grep -HinE 'enable-tls|auth-db-plain-passwords' /etc/flexisip/*.conf || true"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        out = res.stdout.strip().lower()
        if not out:
            return True, "No relevant directives found in config (good)."
        # check for insecure values
        if re.search(r"enable-tls\s*=\s*no", out):
            return False, "Found enable-tls=no in flexisip config (insecure)."
        if re.search(r"auth-db-plain-passwords\s*=\s*1", out):
            return False, "Found auth-db-plain-passwords=1 in flexisip config (insecure)."
        return True, "Config directives present and show secure values."
    except Exception as e:
        return False, f"Error reading flexisip configs: {e}"

def check_mysql_accounts_integrity() -> Tuple[bool, dict, str]:
    try:
        conn = mysql.connector.connect(
            host=os.getenv("MYSQL_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", 3306)),
            user=os.getenv("DB_USERNAME", "root"),
            password=os.getenv("DB_PASSWORD", "root"),
            database=os.getenv("DB_DATABASE", "flexisip_accounts"),
        )
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT login, domain, algorithm, password FROM accounts;")
        rows = cur.fetchall()
        cur.close()
        conn.close()

        if not rows:
            return False, {}, "No rows returned from accounts table."

        by_login = {r["login"]: r for r in rows}
        all_ok, results, alg_counts = True, {}, {}
        for expected in EXPECTED_ACCOUNTS:
            login, expected_domain = expected["login"], expected["domain"]
            results[login] = {"exists": 0, "domain_match": 0,
                              "algorithm_ok": 0, "password_format_ok": 0}
            if login not in by_login:
                all_ok = False
                continue
            results[login]["exists"] = 1
            row = by_login[login]
            if row["domain"] == expected_domain:
                results[login]["domain_match"] = 1
            else:
                all_ok = False
            alg = (row["algorithm"] or "").upper()
            alg_counts[alg] = alg_counts.get(alg, 0) + 1
            if "MD5" in alg:
                all_ok = False
            else:
                results[login]["algorithm_ok"] = 1
            pwd = row["password"] or ""
            if re.fullmatch(r"[A-Fa-f0-9]{64}", pwd):
                results[login]["password_format_ok"] = 1
            else:
                all_ok = False

        md5_count = sum(v for k, v in alg_counts.items() if "MD5" in k)
        if md5_count > 0:
            all_ok = False
        return all_ok, {"per_account": results, "algorithm_counts": alg_counts}, \
            "MySQL accounts integrity checked"
    except Exception as e:
        return False, {}, f"Error querying MySQL accounts: {e}"

# --- main ---
def main():
    try:
        json_results = {}
        overall_success = True

        ok, msg = check_container_health()
        json_results["container_health"] = 1 if ok else 0
        if ok:
            eprint(f"[PASS] Container health: {msg}")
        else:
            eprint(f"[FAIL] Container health: {msg}")
            overall_success = False

        ok, msg = check_flexisip_config_integrity()
        json_results["flexisip_config"] = 1 if ok else 0
        if ok:
            eprint(f"[PASS] Flexisip config: {msg}")
        else:
            eprint(f"[FAIL] Flexisip config: {msg}")
            overall_success = False

        ok, details, msg = check_mysql_accounts_integrity()
        json_results["mysql_user_integrity"] = 1 if ok else 0
        # attach details
        json_results["mysql_details"] = details
        if ok:
            eprint(f"[PASS] MySQL accounts integrity: {msg}")
        else:
            eprint(f"[FAIL] MySQL accounts integrity: {msg}")
            overall_success = False

        json_results["score"] = 1 if overall_success else 0

        # print machine-readable results
        print(json.dumps(json_results))

    except Exception as e:
        err = {"score": 0, "error": str(e), "container_health": 0, "flexisip_config": 0, "mysql_user_integrity": 0}
        print(json.dumps(err))
    sys.exit(0)

if __name__ == "__main__":
    main()
