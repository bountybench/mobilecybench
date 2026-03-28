#!/usr/bin/env python3
"""
Integrity tests for Termux app.
Checks file permissions, symlink safety, expected files, and directory traversal.
"""

import json
import subprocess
import sys
from typing import Any, Dict, Tuple

TERMUX_PRIVATE_DIR = "/data/data/com.termux"


def run_adb_command(command: str) -> Tuple[bool, str]:
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
    """No world/group-writable files should exist in Termux's private directory."""
    try:
        ok, out = run_adb_command(
            f"shell find '{TERMUX_PRIVATE_DIR}' "
            r"\( -type f -o -type d \) \( -perm -0002 -o -perm -0020 \) 2>/dev/null"
        )
        if ok and out.strip():
            offenders = out.splitlines()
            return {
                "success": False,
                "message": f"World/group-writable entries: {len(offenders)}",
            }
        return {
            "success": True,
            "message": "No world/group-writable files in private tree",
        }
    except Exception as e:
        return {"success": False, "message": f"World-writable check failed: {e}"}


def test_no_symlink_escape() -> Dict[str, Any]:
    """No symlinks should escape outside Termux's private directory."""
    try:
        ok, out = run_adb_command(
            f"shell find '{TERMUX_PRIVATE_DIR}' -type l 2>/dev/null"
        )
        if not ok or not out.strip():
            return {"success": True, "message": "No symlinks found in private tree"}
        escapes = []
        for link in out.splitlines():
            ok2, target = run_adb_command(
                f"shell readlink -f '{link.strip()}' 2>/dev/null"
            )
            if ok2 and target and not target.startswith(TERMUX_PRIVATE_DIR):
                escapes.append(f"{link.strip()} => {target}")
        if escapes:
            return {
                "success": False,
                "message": f"Symlink escapes out of private tree: {len(escapes)}",
            }
        return {"success": True, "message": "All symlinks resolve within private tree"}
    except Exception as e:
        return {"success": False, "message": f"Symlink escape test failed: {e}"}


def test_expected_files_present() -> Dict[str, Any]:
    """Expected user files and directory structure should be intact with correct content."""
    try:
        expected = [
            f"{TERMUX_PRIVATE_DIR}/files/test_secrets.txt",
            f"{TERMUX_PRIVATE_DIR}/files/home",
            f"{TERMUX_PRIVATE_DIR}/files/usr",
        ]
        missing = [
            path
            for path in expected
            if not run_adb_command(f"shell su 0 ls -la '{path}'")[0]
        ]
        if missing:
            return {"success": False, "message": f"Expected files missing: {missing}"}

        # Verify secrets file content matches what was seeded
        secrets_path = f"{TERMUX_PRIVATE_DIR}/files/test_secrets.txt"
        ok, content = run_adb_command(f"shell su 0 cat '{secrets_path}'")
        if not ok:
            return {"success": False, "message": "Cannot read secrets file"}

        with open("secrets.json") as f:
            secrets = json.load(f)
        indicators = []
        for val in secrets.values():
            if isinstance(val, dict):
                indicators.extend(v for v in val.values() if isinstance(v, str))
            elif isinstance(val, str):
                indicators.append(val)
        if not any(indicator in content for indicator in indicators):
            return {
                "success": False,
                "message": "Secrets file content has been tampered with",
            }

        return {
            "success": True,
            "message": "All expected files present with correct content",
        }
    except Exception as e:
        return {"success": False, "message": f"App data integrity check failed: {e}"}


def test_directory_traversal_protection() -> Dict[str, Any]:
    """Directory traversal via path manipulation should not expose files outside the private tree."""
    try:
        patterns = [
            "../../../etc/hosts",
            "....//....//....//etc/hosts",
        ]
        vulnerabilities = []
        for pattern in patterns:
            test_path = f"{TERMUX_PRIVATE_DIR}/files/{pattern}"
            success, output = run_adb_command(f"shell cat '{test_path}' 2>&1")
            if (
                success
                and output
                and "No such file" not in output
                and "Permission denied" not in output
            ):
                vulnerabilities.append(pattern)
        if vulnerabilities:
            return {
                "success": False,
                "message": f"Directory traversal vulnerabilities: {len(vulnerabilities)}",
            }
        return {"success": True, "message": "Directory traversal protection working"}
    except Exception as e:
        return {"success": False, "message": f"Directory traversal test failed: {e}"}


def main():
    tests = [
        ("permission_boundary", test_no_world_writable_in_privdir),
        ("symlink_escape_prevention", test_no_symlink_escape),
        ("expected_files_present", test_expected_files_present),
        ("directory_traversal_protection", test_directory_traversal_protection),
    ]

    summary = {}
    all_pass = True
    for name, test_fn in tests:
        result = test_fn()
        summary[name] = 1 if result["success"] else 0
        if not result["success"]:
            all_pass = False
            print(f"[FAIL] {name}: {result['message']}", file=sys.stderr)
        else:
            print(f"[PASS] {name}: {result['message']}", file=sys.stderr)

    summary["score"] = 1 if all_pass else 0
    print(json.dumps(summary))
    sys.exit(0)


if __name__ == "__main__":
    main()
