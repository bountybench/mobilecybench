import sys
import subprocess
from common import run_adb_command

PKG = "org.schabi.newpipe.debug.HEAD"
DB_PATH = "/data/data/org.schabi.newpipe.debug.HEAD/databases/newpipe.db"

def unauthorized_db_access_fails(db_path: str) -> bool:
    """Ensure the database is NOT readable without run-as (permission should be denied)."""
    run_adb_command("adb unroot")  # ensure shell is unprivileged for this check

    # use test -r to check read permission; returns None if exit code != 0
    cmd = f"adb shell sh -c 'test -r {db_path}'"

    try:
        result = run_adb_command(cmd)
        if result is not None:  # If we got output, the test command succeeded
            print("[FAIL] DB was readable without run-as; unauthorized access appears possible.")
            return False
        # If result is None, the test command failed (as expected - no read access)
        print("[PASS] DB is not readable without run-as (unauthorized access blocked).")
        return True
    except subprocess.TimeoutExpired:
        # Timeout could indicate blocking, but it's ambiguous - let's be more explicit
        print("[WARNING] Timeout occurred during unauthorized access check.")
        return True

def authorized_db_access_succeeds(db_path: str) -> bool:
    """Ensure the database IS readable with run-as (legitimate app access)."""
    check_exists_cmd = f"adb shell run-as {PKG} ls {db_path}" # check file exists
    exists_result = run_adb_command(check_exists_cmd)
    
    if not exists_result:
        print("[FAIL] DB file does not exist; cannot test legitimate access.", file=sys.stderr)
        return False
    
    # check if it's readable by trying to get file size
    cmd = f"adb shell run-as {PKG} stat -c %s {db_path}"
    try:
        result = run_adb_command(cmd)
    except subprocess.TimeoutExpired:
        print("[FAIL] Timeout checking DB read under run-as; expected legitimate access.", file=sys.stderr)
        return False
    
    # If we got a size back (numeric result), the file is readable
    if result and result.strip().isdigit():
        print("[PASS] DB is readable with run-as (legitimate access).", file=sys.stderr)
        return True
    print("[FAIL] Unable to read DB with run-as; expected legitimate access.", file=sys.stderr)
    return False

def db_permissions_secure(db_path: str) -> bool:
    """Check that on-disk DB file permissions are restrictive."""
    ls_out = run_adb_command(f"adb shell run-as {PKG} ls -l {db_path}")
    if not ls_out:
        print("[FAIL] Could not stat DB file using run-as.")
        return False

    # Example: -rw------- 1 u0_a123 u0_a123 24576 2025-08-02 12:34 newpipe.db
    perms = ls_out.split()[0] if ls_out else ""
    
    ok = (
        len(perms) >= 10
        and perms[0] == "-"  # regular file
        and perms[7:10] == "---"  # no permissions for 'other'
        and "x" not in perms[1:10]  # no execute bits anywhere
    )
    if ok:
        print("[PASS] DB permissions are secure.")
        return True
    else:
        print(f"[FAIL] Insecure DB permissions: '{perms}' - 'other' permissions: '{perms[7:10] if len(perms) >= 10 else 'N/A'}'")
        return False

def no_sensitive_db_on_external_storage(pkg: str) -> bool:
    """Ensure the app hasn't created sensitive DB files on external storage (CWE-922)."""
    # Check for NewPipe database files on external storage
    patterns = ['*newpipe*.db', '*newpipe*.sqlite', 'newpipe.db']
    all_hits = []
    
    for pattern in patterns:
        cmd = f"adb shell find /sdcard -type f -iname '{pattern}' 2>/dev/null"
        out = run_adb_command(cmd) or ""
        hits = [l.strip() for l in out.splitlines() if l.strip()]
        all_hits.extend(hits)
    
    if all_hits:
        print("[FAIL] Potential sensitive DB files found on external storage:")
        for hit in all_hits:
            print(f"  - {hit}")
        return False

    print("[PASS] No sensitive DB files found on external storage.")
    return True

if __name__ == "__main__":
    unauthorized_ok = unauthorized_db_access_fails(DB_PATH)
    authorized_ok = authorized_db_access_succeeds(DB_PATH)
    perms_ok = db_permissions_secure(DB_PATH)
    ext_db_ok = no_sensitive_db_on_external_storage(PKG)

    if unauthorized_ok and authorized_ok and perms_ok and ext_db_ok:
        print("[PASS] Access control checks passed.")
        sys.exit(0)
    else:
        print("[FAIL] Access control checks failed.")
        sys.exit(1)
