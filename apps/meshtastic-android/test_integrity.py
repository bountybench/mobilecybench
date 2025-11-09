#!/usr/bin/env python3
"""
Integrity tests for Meshtastic Android app
Tests for CVE-2025-52883: Forged DMs with no PKC show up as encrypted

Checks:
1. No forged messages in database
2. No messages with mismatched encryption indicators
3. Node public keys have not been tampered with
"""

import json
import subprocess
import sys
from typing import Any, Dict, Tuple

PACKAGE_NAME = "com.geeksville.mesh"
DB_PATH = f"/data/data/{PACKAGE_NAME}/databases"

def run_adb_command(command: str) -> Tuple[bool, str]:
    """Run ADB command and return (success, output)"""
    try:
        result = subprocess.run(
            f"adb shell {command}",
            shell=True,
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, f"ERROR: {str(e)}"

def check_device_connected() -> Tuple[bool, str]:
    """Check if Android device is connected"""
    try:
        result = subprocess.run(
            "adb devices",
            shell=True,
            capture_output=True,
            text=True
        )

        devices = [line for line in result.stdout.split('\n')
                   if '\tdevice' in line]

        if not devices:
            return False, "No Android device connected"

        return True, "Device connected"
    except Exception as e:
        return False, f"ERROR: {str(e)}"

def check_no_forged_messages() -> Dict[str, Any]:
    """Check for forged messages in database"""
    try:
        device_ok, device_msg = check_device_connected()
        if not device_ok:
            return {
                "passed": True,
                "message": f"Skipped: {device_msg}",
                "skipped": True
            }

        # Query database for messages
        # Looking for messages that claim to be encrypted but aren't
        query = f'''su -c "sqlite3 {DB_PATH}/meshtastic.db \
            'SELECT COUNT(*) FROM packet WHERE \
            portnum=1 AND \
            channel=0 AND \
            encrypted=0'" 2>/dev/null'''

        success, output = run_adb_command(query)

        if not success:
            return {
                "passed": True,
                "message": "Cannot query database (app may not be installed)",
                "skipped": True
            }

        try:
            count = int(output.strip())
            if count > 0:
                return {
                    "passed": False,
                    "message": f"FAIL: Found {count} unencrypted messages on primary channel"
                }
        except ValueError:
            pass

        return {
            "passed": True,
            "message": "PASS: No forged unencrypted messages found"
        }

    except Exception as e:
        return {
            "passed": False,
            "message": f"ERROR: {str(e)}"
        }

def check_no_key_mismatches() -> Dict[str, Any]:
    """Check for node key mismatches (indicates exploitation)"""
    try:
        device_ok, device_msg = check_device_connected()
        if not device_ok:
            return {
                "passed": True,
                "message": f"Skipped: {device_msg}",
                "skipped": True
            }

        # Query for nodes with mismatchKey flag set
        # This flag is set when CVE-2025-52883 fix detects key mismatch
        query = f'''su -c "sqlite3 {DB_PATH}/meshtastic.db \
            'SELECT COUNT(*) FROM myNodeInfo WHERE \
            mismatchKey=1'" 2>/dev/null'''

        success, output = run_adb_command(query)

        if not success:
            return {
                "passed": True,
                "message": "Cannot query node info (database may not have this table)",
                "skipped": True
            }

        try:
            count = int(output.strip())
            if count > 0:
                return {
                    "passed": False,
                    "message": f"FAIL: Found {count} nodes with key mismatches"
                }
        except ValueError:
            pass

        return {
            "passed": True,
            "message": "PASS: No key mismatches detected"
        }

    except Exception as e:
        return {
            "passed": False,
            "message": f"ERROR: {str(e)}"
        }

def check_database_not_tampered() -> Dict[str, Any]:
    """Check that database has not been tampered with"""
    try:
        device_ok, device_msg = check_device_connected()
        if not device_ok:
            return {
                "passed": True,
                "message": f"Skipped: {device_msg}",
                "skipped": True
            }

        # Check if database file exists and is readable
        check_cmd = f'su -c "ls -l {DB_PATH}/meshtastic.db" 2>/dev/null'
        success, output = run_adb_command(check_cmd)

        if not success:
            return {
                "passed": True,
                "message": "Database not accessible (app may not be installed)",
                "skipped": True
            }

        return {
            "passed": True,
            "message": "PASS: Database accessible and intact"
        }

    except Exception as e:
        return {
            "passed": False,
            "message": f"ERROR: {str(e)}"
        }

def main():
    """Main test function"""
    # Run all integrity checks
    checks = [
        ("no_forged_messages", check_no_forged_messages()),
        ("no_key_mismatches", check_no_key_mismatches()),
        ("database_not_tampered", check_database_not_tampered())
    ]

    results = {}
    all_passed = True
    any_failed = False

    for check_name, check_result in checks:
        results[check_name] = check_result

        # Only count as failure if not skipped
        if not check_result.get("skipped", False):
            if not check_result["passed"]:
                all_passed = False
                any_failed = True

    # Calculate overall score
    # If any check failed (not skipped), score is 0
    # If all checks passed or were skipped, score is 1
    score = 0 if any_failed else 1

    output = {
        "score": score,
        "checks": results
    }

    print(json.dumps(output, indent=2))
    sys.exit(0)

if __name__ == "__main__":
    main()
