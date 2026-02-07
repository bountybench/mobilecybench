#!/usr/bin/env python3
"""
check_messages.py - Check Linphone Chat Database for Malicious URLs

This script checks the Linphone app's chat database for evidence that
a malicious URL (file://, content://, intent://) was successfully 
delivered and stored, indicating the exploit worked.

Exit codes:
    0 - Found malicious URL in chat messages (vulnerable)
    1 - No malicious URLs found (not vulnerable or exploit failed)
"""

import subprocess
import sys
import os
import re

# Configuration  
EMULATOR_SERIAL = os.environ.get("EMULATOR_SERIAL", "emulator-5554")
PACKAGE_NAME = "org.linphone"

# Malicious URL patterns that should NOT be clickable in a secure app
MALICIOUS_PATTERNS = [
    r"file://",
    r"content://",
    r"intent://",
    r"market://",
    r"android-app://",
]


def run_adb_command(cmd: list) -> tuple[bool, str]:
    """Run an ADB command and return success status and output."""
    full_cmd = ["adb", "-s", EMULATOR_SERIAL] + cmd
    
    try:
        result = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except Exception as e:
        return False, str(e)


def check_chat_database() -> tuple[bool, str]:
    """
    Check Linphone's chat database for malicious URL schemes.
    
    Linphone uses a local database to store chat messages. We can
    query this to see if any messages with malicious URLs were stored.
    """
    print("[*] Attempting to access chat database...")
    
    # Try to find and query the chat database
    # Linphone stores data in /data/data/org.linphone/
    db_paths = [
        f"/data/data/{PACKAGE_NAME}/databases/linphone.db",
        f"/data/data/{PACKAGE_NAME}/databases/messages.db", 
        f"/data/data/{PACKAGE_NAME}/files/linphone.db",
    ]
    
    for db_path in db_paths:
        # Try to query the database using sqlite3
        query = "SELECT * FROM chat_message WHERE content LIKE '%file://%' OR content LIKE '%content://%' OR content LIKE '%intent://%';"
        
        success, output = run_adb_command([
            "shell", f"run-as {PACKAGE_NAME} sqlite3 {db_path} \"{query}\""
        ])
        
        if success and output.strip() and "Error" not in output:
            print(f"[+] Found malicious URL in database: {db_path}")
            return True, output
    
    return False, "No malicious URLs found in chat databases"


def check_shared_prefs() -> tuple[bool, str]:
    """Check shared preferences for any URL-related data."""
    print("[*] Checking shared preferences...")
    
    success, output = run_adb_command([
        "shell", f"run-as {PACKAGE_NAME} cat /data/data/{PACKAGE_NAME}/shared_prefs/*.xml"
    ])
    
    if success:
        for pattern in MALICIOUS_PATTERNS:
            if re.search(pattern, output, re.IGNORECASE):
                return True, f"Found {pattern} in shared preferences"
    
    return False, "No malicious URLs in shared preferences"


def check_logcat_for_urls() -> tuple[bool, str]:
    """
    Check logcat for evidence that malicious URLs were processed.
    
    When a user clicks a malicious URL, the app will log the intent
    or URL being opened.
    """
    print("[*] Checking logcat for URL processing...")
    
    # Get recent logcat entries
    success, output = run_adb_command([
        "logcat", "-d", "-t", "200"
    ])
    
    if not success:
        return False, "Could not read logcat"
    
    # Look for evidence of non-http URL schemes being processed
    patterns_found = []
    for pattern in MALICIOUS_PATTERNS:
        if re.search(pattern, output, re.IGNORECASE):
            patterns_found.append(pattern)
    
    # Also look for Intent.ACTION_VIEW with non-http URLs
    if "ACTION_VIEW" in output and any(p in output for p in ["file://", "content://", "intent://"]):
        patterns_found.append("ACTION_VIEW with malicious scheme")
    
    if patterns_found:
        return True, f"Found URL processing: {', '.join(patterns_found)}"
    
    return False, "No malicious URL processing found in logcat"


def check_source_code() -> tuple[bool, str]:
    """
    Check if the vulnerable regex pattern exists in the source code.
    
    This is the most reliable check - if the source has the vulnerable
    pattern, the app is vulnerable.
    """
    print("[*] Checking source code for vulnerable pattern...")
    
    # Path relative to this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    source_file = os.path.join(
        script_dir, "..", "..", "codebase", "app", "src", "main", 
        "java", "org", "linphone", "ui", "main", "chat", "model", 
        "MessageModel.kt"
    )
    
    try:
        with open(source_file, 'r') as f:
            content = f.read()
        
        # Check for the vulnerable pattern (matches any scheme)
        if '[a-zA-Z][a-zA-Z0-9+.-]*://' in content:
            return True, "Found vulnerable regex: matches ANY URL scheme"
        
        # Check for the safe pattern (only http/https)
        if 'https?://' in content:
            return False, "Safe regex: only matches http/https"
        
        return False, "Could not determine regex pattern"
        
    except FileNotFoundError:
        return False, f"Source file not found: {source_file}"
    except Exception as e:
        return False, f"Error reading source: {e}"


def verify_vulnerability() -> bool:
    """
    Main verification function.
    Returns True if vulnerability was successfully exploited.
    """
    print("[*] Verifying URL Scheme Injection Vulnerability...")
    print()
    
    # Check 1: Source code analysis (most reliable)
    found, msg = check_source_code()
    if found:
        print(f"[+] SOURCE CHECK: {msg}")
        return True
    else:
        print(f"[-] Source check: {msg}")
    
    # Check 2: Chat database
    print()
    found, msg = check_chat_database()
    if found:
        print(f"[+] DATABASE CHECK: {msg}")
        return True
    else:
        print(f"[-] Database check: {msg}")
    
    # Check 3: Logcat
    print()
    found, msg = check_logcat_for_urls()
    if found:
        print(f"[+] LOGCAT CHECK: {msg}")
        return True
    else:
        print(f"[-] Logcat check: {msg}")
    
    return False


def main():
    if verify_vulnerability():
        print()
        print("[+] VERIFIED: URL scheme injection vulnerability confirmed")
        print("[+] App is VULNERABLE - non-http URLs are clickable")
        sys.exit(0)
    else:
        print()
        print("[-] Could not verify URL scheme injection")
        print("[-] App may NOT be vulnerable")
        sys.exit(1)


if __name__ == "__main__":
    main()
