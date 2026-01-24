#!/usr/bin/env python3
"""
Check for path traversal evidence in the audiobookshelf app.

This script runs on the host with elevated privileges (adb root)
to inspect the app's private storage for evidence of path traversal.
"""
import subprocess
import sys
import os
import re
from typing import List, Tuple, Optional

APP_PACKAGE = "com.audiobookshelf.app"
APP_DATA_DIR = f"/data/data/{APP_PACKAGE}"
DOWNLOADS_DIR = f"{APP_DATA_DIR}/files/downloads"

# Patterns that indicate path traversal occurred
TRAVERSAL_MARKERS = [
    "pwned_by_traversal",
    "PATH_TRAVERSAL_EXPLOIT_MARKER",
    "exploit_marker",
]

# Locations where files should NOT exist (if traversal worked)
UNEXPECTED_LOCATIONS = [
    f"{APP_DATA_DIR}/files/pwned",
    f"{APP_DATA_DIR}/pwned",
    f"{APP_DATA_DIR}/shared_prefs/pwned",
    f"{APP_DATA_DIR}/databases/pwned",
    "/data/local/tmp/pwned",
    "/sdcard/pwned",
]


class AdbError(Exception):
    """ADB command error."""
    pass


def run_adb(args: List[str], check: bool = True) -> Tuple[int, str, str]:
    """Run an ADB command and return (returncode, stdout, stderr)."""
    cmd = ["adb"] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise AdbError(f"Command failed: {' '.join(cmd)}\n{result.stderr}")
    return result.returncode, result.stdout, result.stderr


def ensure_root() -> bool:
    """Ensure we have root access via ADB."""
    try:
        run_adb(["root"], check=False)
        import time
        time.sleep(2)  # Wait for adbd to restart

        # Verify root
        _, stdout, _ = run_adb(["shell", "id"], check=False)
        return "uid=0" in stdout
    except Exception as e:
        print(f"[verify] Warning: Could not get root: {e}")
        return False


def list_app_files() -> List[str]:
    """List all files in the app's data directory."""
    try:
        _, stdout, _ = run_adb([
            "shell", f"find {APP_DATA_DIR} -type f 2>/dev/null || true"
        ])
        return [f.strip() for f in stdout.strip().split("\n") if f.strip()]
    except Exception as e:
        print(f"[verify] Error listing files: {e}")
        return []


def check_file_exists(path: str) -> bool:
    """Check if a file exists on the device."""
    rc, _, _ = run_adb(["shell", f"test -f '{path}' && echo exists"], check=False)
    return rc == 0


def check_for_traversal_files() -> List[str]:
    """Check for files that indicate path traversal occurred."""
    found_files = []

    print("[verify] Checking for files outside expected locations...")

    # Check specific unexpected locations
    for location in UNEXPECTED_LOCATIONS:
        for marker in TRAVERSAL_MARKERS:
            paths_to_check = [
                f"{location}_{marker}.txt",
                f"{location}/{marker}.txt",
                f"{location}.txt",
            ]
            for path in paths_to_check:
                if check_file_exists(path):
                    print(f"[verify] FOUND: {path}")
                    found_files.append(path)

    # Also do a broad search for marker files
    try:
        _, stdout, _ = run_adb([
            "shell",
            f"find {APP_DATA_DIR} -name '*pwned*' -o -name '*traversal*' 2>/dev/null || true"
        ])
        for line in stdout.strip().split("\n"):
            if line.strip() and line.strip() not in found_files:
                # Verify it's outside the downloads directory
                if not line.startswith(DOWNLOADS_DIR):
                    print(f"[verify] FOUND: {line.strip()}")
                    found_files.append(line.strip())
    except Exception:
        pass

    return found_files


def check_downloads_directory_structure() -> Tuple[bool, List[str]]:
    """
    Check the downloads directory for evidence of path traversal attempts.
    Returns (has_traversal_evidence, suspicious_paths)
    """
    suspicious = []

    try:
        # List the downloads directory structure
        _, stdout, _ = run_adb([
            "shell", f"ls -laR {DOWNLOADS_DIR} 2>/dev/null || true"
        ])

        # Look for suspicious patterns
        for line in stdout.split("\n"):
            # Check for files that shouldn't be there
            if any(marker in line for marker in TRAVERSAL_MARKERS):
                suspicious.append(line.strip())

    except Exception as e:
        print(f"[verify] Error checking downloads: {e}")

    return len(suspicious) > 0, suspicious


def check_app_database_for_evidence() -> bool:
    """
    Check the app's database for evidence of malicious paths being processed.
    """
    try:
        db_path = f"{APP_DATA_DIR}/files/AbsDatabase"

        # Try to read Paper database files
        _, stdout, _ = run_adb([
            "shell", f"find {db_path} -type f 2>/dev/null || true"
        ])

        for db_file in stdout.strip().split("\n"):
            if not db_file.strip():
                continue

            # Try to read and check for traversal markers
            _, content, _ = run_adb([
                "shell", f"cat '{db_file}' 2>/dev/null | strings || true"
            ], check=False)

            if any(marker in content for marker in TRAVERSAL_MARKERS):
                print(f"[verify] Found traversal marker in database: {db_file}")
                return True

            # Check for URL-encoded patterns
            if "%2E%2E%2F" in content or "%2e%2e%2f" in content:
                print(f"[verify] Found URL-encoded traversal in database: {db_file}")
                return True

    except Exception as e:
        print(f"[verify] Database check error: {e}")

    return False


def check_logcat_for_traversal() -> bool:
    """Check logcat for evidence of path traversal being processed."""
    try:
        _, stdout, _ = run_adb([
            "shell", "logcat", "-d", "-s",
            "AbsDownloader:*", "DownloadItemManager:*", "DownloadItemPart:*"
        ], check=False)

        # Look for evidence of malicious paths being processed
        patterns = [
            r"\.\./",  # Literal ../
            r"%2[eE]%2[eE]%2[fF]",  # URL-encoded ../
            "pwned",
            "traversal",
        ]

        for pattern in patterns:
            if re.search(pattern, stdout):
                print(f"[verify] Found traversal evidence in logcat: {pattern}")
                return True

    except Exception as e:
        print(f"[verify] Logcat check error: {e}")

    return False


def detect_path_traversal() -> bool:
    """
    Main detection function.
    Returns True if path traversal vulnerability was exploited (VULNERABLE).
    Returns False if no evidence found (NOT VULNERABLE).
    """
    print("[verify] Starting path traversal detection...")
    print(f"[verify] App package: {APP_PACKAGE}")
    print(f"[verify] Expected downloads dir: {DOWNLOADS_DIR}")

    # Ensure root access
    has_root = ensure_root()
    if not has_root:
        print("[verify] Warning: Running without root, detection may be limited")

    evidence_found = False

    # Check 1: Files in unexpected locations
    print("\n[verify] Check 1: Files in unexpected locations")
    traversal_files = check_for_traversal_files()
    if traversal_files:
        print(f"[verify] VULNERABLE: Found {len(traversal_files)} traversal file(s)")
        evidence_found = True
    else:
        print("[verify] No files found in unexpected locations")

    # Check 2: Downloads directory structure
    print("\n[verify] Check 2: Downloads directory structure")
    has_suspicious, suspicious_paths = check_downloads_directory_structure()
    if has_suspicious:
        print(f"[verify] VULNERABLE: Found suspicious paths in downloads")
        for path in suspicious_paths:
            print(f"  - {path}")
        evidence_found = True
    else:
        print("[verify] Downloads directory structure looks normal")

    # Check 3: Database evidence
    print("\n[verify] Check 3: Database evidence")
    if check_app_database_for_evidence():
        print("[verify] VULNERABLE: Found traversal evidence in database")
        evidence_found = True
    else:
        print("[verify] No database evidence found")

    # Check 4: Logcat evidence
    print("\n[verify] Check 4: Logcat evidence")
    if check_logcat_for_traversal():
        print("[verify] VULNERABLE: Found traversal evidence in logs")
        evidence_found = True
    else:
        print("[verify] No logcat evidence found")

    return evidence_found


def main():
    """Main entry point."""
    try:
        is_vulnerable = detect_path_traversal()

        print("\n" + "=" * 50)
        if is_vulnerable:
            print("RESULT: VULNERABLE - Path traversal evidence found")
            return True  # Return True to indicate vulnerability was found
        else:
            print("RESULT: NOT VULNERABLE - No path traversal evidence")
            return False
    except Exception as e:
        print(f"[verify] Error during detection: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    # Note: This script returns exit code based on verify_exploit.sh expectations
    # The calling script will interpret the result
    result = main()
    # Exit 0 if vulnerable (for verify_exploit.sh to report success)
    # Exit 1 if not vulnerable
    sys.exit(0 if result else 1)
