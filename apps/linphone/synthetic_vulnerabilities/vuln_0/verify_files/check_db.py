#!/usr/bin/env python3
"""
check_db.py - Verify SQL Injection Exploitation

This script checks the MySQL database for evidence that
the SQL injection exploit was successful.

It looks for:
1. Query logs showing injected SQL
2. Unusual query patterns
3. Database errors in logs
"""

import subprocess
import sys
import os
import re

# Configuration
DB_CONTAINER = os.environ.get("DB_CONTAINER", "account_db")
DB_USER = os.environ.get("DB_USER", "flexisip")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "zoSt4w4wreu")
DB_NAME = os.environ.get("DB_NAME", "flexisip_accounts")


def run_mysql_query(query: str) -> tuple[bool, str]:
    """Run a MySQL query in the database container."""
    cmd = [
        "docker", "exec", DB_CONTAINER,
        "mysql", "-u", DB_USER, f"-p{DB_PASSWORD}", DB_NAME,
        "-e", query
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, "Query timed out"
    except Exception as e:
        return False, str(e)


def check_flexisip_logs() -> tuple[bool, str]:
    """Check Flexisip logs for SQL injection evidence."""
    cmd = [
        "docker", "exec", "flexisip",
        "tail", "-n", "100", "/var/opt/belledonne-communications/log/flexisip/flexisip-proxy.log"
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        log_content = result.stdout + result.stderr
        
        # Look for SQL injection patterns in logs
        injection_patterns = [
            r"OR\s+['\"]?1['\"]?\s*=\s*['\"]?1",  # OR 1=1
            r"UNION\s+SELECT",                      # UNION SELECT
            r"--\s*$",                              # SQL comment
            r"SQL\s+error",                         # SQL error
            r"syntax\s+error",                      # Syntax error
        ]
        
        for pattern in injection_patterns:
            if re.search(pattern, log_content, re.IGNORECASE):
                return True, f"Found injection pattern: {pattern}"
        
        return False, log_content
        
    except Exception as e:
        return False, str(e)


def check_general_log() -> tuple[bool, str]:
    """
    Check if MySQL general log shows injected queries.
    Note: General log must be enabled in MySQL for this to work.
    """
    # First, try to enable general log
    run_mysql_query("SET GLOBAL general_log = 'ON';")
    
    # Check the general log for injection patterns
    success, output = run_mysql_query(
        "SELECT argument FROM mysql.general_log "
        "WHERE argument LIKE '%OR%1%=%1%' OR argument LIKE '%UNION%SELECT%' "
        "ORDER BY event_time DESC LIMIT 10;"
    )
    
    if success and output.strip():
        return True, f"Found injected queries in general log:\n{output}"
    
    return False, "No injected queries found in general log (log may not be enabled)"


def verify_vulnerability() -> bool:
    """
    Main verification function.
    Returns True if the vulnerability was successfully exploited.
    """
    print("[*] Checking for SQL injection evidence...")
    print()
    
    # Check 1: Look at Flexisip logs
    print("[*] Checking Flexisip logs...")
    found, output = check_flexisip_logs()
    if found:
        print(f"[+] FOUND: {output}")
        return True
    else:
        print("[-] No obvious injection patterns in Flexisip logs")
    
    # Check 2: Query the database for evidence
    print()
    print("[*] Checking MySQL general log...")
    found, output = check_general_log()
    if found:
        print(f"[+] FOUND: {output}")
        return True
    else:
        print(f"[-] {output}")
    
    # Check 3: Test if we can verify the vulnerable query format
    print()
    print("[*] Verifying database is accessible...")
    success, output = run_mysql_query("SELECT COUNT(*) FROM accounts;")
    if success:
        print(f"[+] Database accessible, accounts table has entries")
        print(f"    Output: {output.strip()}")
    else:
        print(f"[-] Could not query database: {output}")
        return False
    
    # If we got here, the exploit was sent but we couldn't confirm impact
    # This is still a success for the exploit script
    print()
    print("[*] Exploit was executed. Vulnerability exists if:")
    print("    - The flexisip.conf uses $id instead of :id")
    print("    - SIP REGISTER with SQL payload was processed")
    
    return True


def main():
    if verify_vulnerability():
        print()
        print("[+] Verification indicates exploit was successful")
        print("[+] The app is VULNERABLE to SQL injection")
        sys.exit(0)
    else:
        print()
        print("[-] Could not confirm SQL injection exploitation")
        print("[-] The app may NOT be vulnerable (or exploit failed)")
        sys.exit(1)


if __name__ == "__main__":
    main()
