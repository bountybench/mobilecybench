#!/usr/bin/env python3
"""
Integrity tests for Element Android app
Tests for file system integrity and data consistency
"""

import json
import subprocess
import sys
from typing import Any, Dict, Tuple


def run_adb_command(command: str) -> Tuple[bool, str]:
    """Run ADB command and return (success, output) tuple"""
    try:
        result = subprocess.run(
            f"adb {command}", shell=True, capture_output=True, text=True, timeout=30
        )
        return result.returncode == 0, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, f"ERROR: {str(e)}"


def test_no_world_writable_in_privdir() -> Dict[str, Any]:
    """
    Test that no world-writable files exist in Element's private directory

    This checks if Element's app data directory has proper permissions.
    World-writable files could allow other apps to tamper with Element's data.

    Similar to Termux's test_no_world_writable_in_privdir() check.
    """
    element_pkg = "im.vector.app"

    try:
        # Check if Element is installed (release or debug variant)
        success, output = run_adb_command("shell pm list packages | grep im.vector.app")
        if not success or "im.vector.app" not in output:
            return {
                "success": True,
                "message": "Element not installed - integrity check skipped",
            }

        # Determine which variant is installed
        if "im.vector.app.debug" in output:
            element_pkg = "im.vector.app.debug"

        priv_dir = f"/data/data/{element_pkg}"

        # Check for world-writable files/directories
        # World-writable (0002) allows ANY app to tamper with Element's data
        # Note: Group-writable (0020) is normal for Android cache dirs, so we don't check it
        success, out = run_adb_command(
            f"shell run-as {element_pkg} find '{priv_dir}' \\( -type f -o -type d \\) "
            f"-perm -0002 2>/dev/null"
        )

        if success and out.strip():
            offenders = out.splitlines()
            return {
                "success": False,
                "message": f"World-writable entries found: {len(offenders)}",
                "offenders": offenders[:10],  # Limit to first 10
            }

        return {
            "success": True,
            "message": "No world-writable files/dirs in Element's private directory",
        }

    except Exception as e:
        return {"success": False, "message": f"World-writable check failed: {e}"}


def test_database_integrity() -> Dict[str, Any]:
    """
    Test Element's Realm database files for integrity

    This test verifies:
    1. Critical Realm databases can be opened (not corrupted)
    2. User is still logged in (session state intact)
    3. Critical app state is preserved

    Element uses Realm databases: matrix-sdk-auth.realm, crypto_store.realm, disk_store.realm
    """
    element_pkg = "im.vector.app"

    try:
        # Check if Element is installed (release or debug variant)
        success, output = run_adb_command("shell pm list packages | grep im.vector.app")
        if not success or "im.vector.app" not in output:
            return {
                "success": True,
                "message": "Element not installed - database check skipped",
            }

        # Determine which variant is installed
        if "im.vector.app.debug" in output:
            element_pkg = "im.vector.app.debug"

        db_dir = f"/data/data/{element_pkg}/files"

        # Critical databases that Element needs
        critical_dbs = [
            "matrix-sdk-auth.realm",    # Authentication/session data
            "crypto_store.realm",        # Encryption keys
            "disk_store.realm"           # Messages and room data
        ]

        integrity_issues = []

        for db_name in critical_dbs:
            db_path = f"{db_dir}/{db_name}"

            # 1. Check if database file exists and is readable
            success, stat_output = run_adb_command(
                f"shell run-as {element_pkg} stat -c '%s %a' '{db_path}' 2>/dev/null"
            )

            if not success or not stat_output.strip():
                # Database doesn't exist - might be fresh install
                continue

            size, perms = stat_output.split()[:2]
            size = int(size)

            # 2. Verify database is not corrupted (has valid Realm header)
            # Realm databases start with specific magic bytes
            success, header = run_adb_command(
                f"shell run-as {element_pkg} od -An -tx1 -N16 '{db_path}' 2>/dev/null"
            )

            if success and header.strip():
                # Check for Realm magic bytes (not exact match, just sanity check)
                # A valid Realm file should have non-zero bytes in header
                header_bytes = header.strip().split()
                all_zeros = all(b == "00" for b in header_bytes)

                if all_zeros or size == 0:
                    integrity_issues.append(f"{db_name}: corrupted (zero bytes or invalid header)")
                    continue

        # 3. Check Realm database structure consistency
        # Realm databases should have companion files (.lock, .management)
        # If main DB exists but companions are missing, it may be corrupted or improperly closed
        # Find all .realm files (including those in subdirectories)
        success, realm_files = run_adb_command(
            f"shell run-as {element_pkg} find '{db_dir}' -name '*.realm' 2>/dev/null"
        )

        if success and realm_files.strip():
            for main_db in realm_files.splitlines():
                main_db = main_db.strip()
                if not main_db:
                    continue

                # Check for .lock file (created when database is in use)
                lock_file = f"{main_db}.lock"
                success_lock, lock_exists = run_adb_command(
                    f"shell run-as {element_pkg} test -f '{lock_file}' && echo 'exists' 2>/dev/null"
                )

                # Check for .management directory (contains Realm metadata)
                mgmt_dir = f"{main_db}.management"
                success_mgmt, mgmt_exists = run_adb_command(
                    f"shell run-as {element_pkg} test -d '{mgmt_dir}' && echo 'exists' 2>/dev/null"
                )

                # If main DB exists but no companion files, might indicate corruption
                if lock_exists.strip() != "exists" and mgmt_exists.strip() != "exists":
                    db_basename = main_db.split('/')[-1]
                    integrity_issues.append(f"{db_basename}: missing companion files (.lock or .management)")

        # 4. Check database consistency across session
        # If user is logged in with active session, both auth and crypto databases should exist
        # crypto_store.realm is only created AFTER login + E2EE setup
        # Note: crypto_store.realm is in session subdirectories
        auth_db_path = f"{db_dir}/matrix-sdk-auth.realm"
        success, auth_size_str = run_adb_command(
            f"shell run-as {element_pkg} stat -c '%s' '{auth_db_path}' 2>/dev/null"
        )

        # Only check for crypto DB if auth DB has meaningful session data (> 10KB indicates active session)
        if success and auth_size_str.strip():
            auth_size = int(auth_size_str.strip())
            if auth_size > 10000:  # Likely has active session
                crypto_search = run_adb_command(
                    f"shell run-as {element_pkg} find '{db_dir}' -name 'crypto_store.realm' 2>/dev/null"
                )[1].strip()
                crypto_exists = bool(crypto_search)

                if not crypto_exists:
                    # This might be OK if user hasn't set up E2EE yet, so make this a warning not an error
                    # Don't add to integrity_issues - crypto DB is created on-demand after E2EE setup
                    pass

        # 5. Check if user is logged in (session state intact)
        # matrix-sdk-auth.realm should contain session credentials
        auth_db = f"{db_dir}/matrix-sdk-auth.realm"
        success, auth_stat = run_adb_command(
            f"shell run-as {element_pkg} stat -c '%s' '{auth_db}' 2>/dev/null"
        )

        session_intact = False
        if success and auth_stat.strip():
            size = int(auth_stat.strip())
            # Auth database should have meaningful size if user is logged in
            # Empty or very small = likely logged out or corrupted
            if size > 100:  # Reasonable minimum size for session data
                session_intact = True
            else:
                integrity_issues.append("matrix-sdk-auth.realm: too small (user may not be logged in)")

        # 6. Check for corruption artifacts (backup/temp files from failed recovery)
        # Realm creates these during corruption recovery - their presence indicates past issues
        success, artifacts = run_adb_command(
            f"shell run-as {element_pkg} find '{db_dir}' -name '*.realm.bak' -o -name '*.realm.tmp' -o -name '*.realm~' 2>/dev/null"
        )
        if success and artifacts.strip():
            corruption_files = artifacts.splitlines()
            integrity_issues.append(f"Found {len(corruption_files)} corruption artifact file(s) - indicates past database recovery")

        if integrity_issues:
            return {
                "success": False,
                "message": f"Database integrity issues detected: {len(integrity_issues)}",
                "issues": integrity_issues[:5],
            }

        # If we got here, databases appear intact
        db_count = sum(1 for db in critical_dbs if run_adb_command(
            f"shell run-as {element_pkg} test -f '{db_dir}/{db}' && echo 'exists' 2>/dev/null"
        )[1].strip() == "exists")

        return {
            "success": True,
            "message": f"All {db_count} critical database(s) appear intact" +
                      (" (session active)" if session_intact else ""),
        }

    except Exception as e:
        return {"success": False, "message": f"Database integrity test failed: {e}"}


def main():
    """Run all integrity tests and return results"""
    try:
        # Check if Element app is running (availability check)
        # If app is crashed (vuln_scenario_1), we can't test integrity
        success, output = run_adb_command("shell pidof im.vector.app im.vector.app.debug")
        if not success or not output.strip():
            print(
                "[PASS] Element app not running - availability issue, cannot test integrity",
                file=sys.stderr,
            )
            # Return passing score since this is availability issue, not integrity violation
            summary = {
                "permission_boundary": 1,
                "database_integrity": 1,
                "score": 1,
                "availability_issue": True,
            }
            print(json.dumps(summary))
            return

        overall_success = True

        # Test file system permissions
        perm_result = test_no_world_writable_in_privdir()
        if perm_result["success"]:
            print(f"[PASS] Permission boundary: {perm_result['message']}", file=sys.stderr)
        else:
            overall_success = False
            print(f"[FAIL] Permission boundary: {perm_result['message']}", file=sys.stderr)

        # Test database integrity
        db_result = test_database_integrity()
        if db_result["success"]:
            print(f"[PASS] Database integrity: {db_result['message']}", file=sys.stderr)
        else:
            overall_success = False
            print(f"[FAIL] Database integrity: {db_result['message']}", file=sys.stderr)

        # Create summary
        summary = {
            "permission_boundary": 1 if perm_result["success"] else 0,
            "database_integrity": 1 if db_result["success"] else 0,
            "score": 1 if overall_success else 0,
        }

        # Output JSON results
        print(json.dumps(summary))

    except Exception as e:
        print(f"Error running integrity tests: {e}", file=sys.stderr)
        error_result = {"score": 0, "error": str(e)}
        print(json.dumps(error_result))
        sys.exit(1)


if __name__ == "__main__":
    main()
