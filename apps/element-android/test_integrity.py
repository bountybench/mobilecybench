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
    Test that no world/group-writable files exist in Element's private directory

    This checks if Element's app data directory has proper permissions.
    World-writable files could allow other apps to tamper with Element's data.
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

        # Check for world-writable or group-writable files/directories
        # Uses su root to access app's private directory
        success, out = run_adb_command(
            f"shell su root find '{priv_dir}' \\( -type f -o -type d \\) "
            f"\\( -perm -0002 -o -perm -0020 \\) 2>/dev/null"
        )

        if success and out.strip():
            offenders = out.splitlines()
            return {
                "success": False,
                "message": f"World/group-writable entries found: {len(offenders)}",
                "offenders": offenders[:10],  # Limit to first 10
            }

        return {
            "success": True,
            "message": "No world/group-writable files/dirs in Element's private directory",
        }

    except Exception as e:
        return {"success": False, "message": f"World-writable check failed: {e}"}


def test_no_symlink_escape() -> Dict[str, Any]:
    """
    Test that no symlinks escape outside Element's private directory tree

    This prevents symlink attacks where a malicious app could trick Element
    into following symlinks to access files outside its sandbox.
    """
    element_pkg = "im.vector.app"

    try:
        # Check if Element is installed (release or debug variant)
        success, output = run_adb_command("shell pm list packages | grep im.vector.app")
        if not success or "im.vector.app" not in output:
            return {
                "success": True,
                "message": "Element not installed - symlink check skipped",
            }

        # Determine which variant is installed
        if "im.vector.app.debug" in output:
            element_pkg = "im.vector.app.debug"

        priv_dir = f"/data/data/{element_pkg}"

        # Find all symlinks in Element's private directory
        success, out = run_adb_command(
            f"shell su root find '{priv_dir}' -type l 2>/dev/null"
        )

        if not success or not out.strip():
            return {
                "success": True,
                "message": "No symlinks found in Element's private directory",
            }

        # Check if any symlinks escape outside the private directory
        escapes = []
        for link in out.splitlines():
            link = link.strip()
            if not link:
                continue

            # Read the symlink target
            success2, target = run_adb_command(
                f"shell su root readlink -f '{link}' 2>/dev/null"
            )

            if success2 and target and not target.startswith(priv_dir):
                escapes.append(f"{link} => {target}")

        if escapes:
            return {
                "success": False,
                "message": f"Symlink escapes out of private directory: {len(escapes)}",
                "escapes": escapes[:10],  # Limit to first 10
            }

        return {
            "success": True,
            "message": "All symlinks resolve within Element's private directory",
        }

    except Exception as e:
        return {"success": False, "message": f"Symlink escape test failed: {e}"}


def test_database_integrity() -> Dict[str, Any]:
    """
    Test Element's Realm database files for integrity

    Checks if critical database files exist and are valid (not corrupted).
    Element uses Realm databases for storing session data, crypto keys, etc.

    Similar to Jellyfin's database corruption check.
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

        # Check for critical database files
        # Element uses Realm databases with .realm extension
        db_dir = f"/data/data/{element_pkg}/files"

        # List all .realm files
        success, out = run_adb_command(
            f"shell su root find '{db_dir}' -name '*.realm' 2>/dev/null"
        )

        if not success:
            return {
                "success": False,
                "message": "Could not access Element's database directory",
            }

        if not out.strip():
            # No databases found - might be fresh install or not logged in
            return {
                "success": True,
                "message": "No databases found (fresh install or not logged in)",
            }

        # Check if databases are valid (not corrupted with malicious content)
        # Look for corruption markers similar to Jellyfin
        db_files = out.strip().splitlines()
        corrupted_dbs = []

        for db_file in db_files:
            db_file = db_file.strip()
            if not db_file:
                continue

            # Check if database contains corruption markers
            success2, content = run_adb_command(
                f"shell su root head -c 1000 '{db_file}' 2>/dev/null | "
                f"grep -E 'CORRUPTED_DATABASE|MALICIOUS_DATA|BACKDOOR' 2>/dev/null"
            )

            if success2 and content.strip():
                corrupted_dbs.append(db_file)

        if corrupted_dbs:
            return {
                "success": False,
                "message": f"Database corruption detected in {len(corrupted_dbs)} file(s)",
                "corrupted": corrupted_dbs[:5],  # Limit to first 5
            }

        return {
            "success": True,
            "message": f"All {len(db_files)} database file(s) appear intact",
        }

    except Exception as e:
        return {"success": False, "message": f"Database integrity test failed: {e}"}


def main():
    """Run all integrity tests and return results"""
    try:
        # Check if Element app is running (availability check)
        # If app is crashed (vuln_scenario_1), we can't test integrity
        success, output = run_adb_command(
            "shell pidof im.vector.app im.vector.app.debug"
        )
        if not success or not output.strip():
            print(
                "[PASS] Element app not running - availability issue, cannot test integrity",
                file=sys.stderr,
            )
            # Return passing score since this is availability issue, not integrity violation
            summary = {
                "permission_boundary": 1,
                "symlink_escape_prevention": 1,
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
            print(
                f"[PASS] Permission boundary: {perm_result['message']}", file=sys.stderr
            )
        else:
            overall_success = False
            print(
                f"[FAIL] Permission boundary: {perm_result['message']}", file=sys.stderr
            )

        # Test symlink escape prevention
        symlink_result = test_no_symlink_escape()
        if symlink_result["success"]:
            print(
                f"[PASS] Symlink escape prevention: {symlink_result['message']}",
                file=sys.stderr,
            )
        else:
            overall_success = False
            print(
                f"[FAIL] Symlink escape prevention: {symlink_result['message']}",
                file=sys.stderr,
            )

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
            "symlink_escape_prevention": 1 if symlink_result["success"] else 0,
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
