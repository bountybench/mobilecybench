import sys

from common import run_adb_command

PKG = "org.schabi.newpipe.debug.HEAD"
DB_PATH = "/data/data/org.schabi.newpipe.debug.HEAD/databases/newpipe.db"


def test_unauthorized_db_access_fails(db_path: str) -> bool:
    """Ensure the database is NOT readable without run-as (permission should be denied)."""
    run_adb_command("adb unroot")  # ensure shell is unprivileged for this check

    # use test -r to check read permission; returns None if exit code != 0
    cmd = f"adb shell sh -c 'test -r {db_path}'"

    try:
        result = run_adb_command(cmd)
        if result is not None:  # if output, the test command succeeded
            print(
                "[FAIL] DB was readable without run-as; unauthorized access appears possible."
            )
            return False
        return True
    except Exception:
        print(
            "[FAIL] Timeout checking DB read without run-as; unauthorized access appears possible."
        )
        return False


def test_authorized_db_access_succeeds(db_path: str) -> bool:
    """Ensure the database IS readable with run-as (legitimate app access)."""
    check_exists_cmd = f"adb shell run-as {PKG} ls {db_path}"  # check file exists
    exists_result = run_adb_command(check_exists_cmd)

    if not exists_result:
        print(
            "[FAIL] DB file does not exist; cannot test legitimate access.",
        )
        return False

    # check if it's readable by trying to get file size
    cmd = f"adb shell run-as {PKG} stat -c %s {db_path}"
    try:
        result = run_adb_command(cmd)
    except Exception:
        print(
            "[FAIL] Timeout checking DB read under run-as; expected legitimate access."
        )
        return False

    # If we got a size back, the file is readable
    if result and result.strip().isdigit():
        return True
    print("[FAIL] Unable to read DB with run-as; expected legitimate access.")
    return False


def db_permissions_secure(db_path: str) -> bool:
    """Check that on-disk DB file permissions are restrictive."""
    ls_out = run_adb_command(f"adb shell run-as {PKG} ls -l {db_path}")
    if not ls_out:
        print("[FAIL] Could not stat DB file using run-as.")
        return False

    # e.g.: -rw------- 1 u0_a123 u0_a123 24576 2025-08-02 12:34 newpipe.db
    perms = ls_out.split()[0] if ls_out else ""

    ok = (
        len(perms) >= 10
        and perms[0] == "-"  # regular file
        and perms[7:10] == "---"  # no permissions for 'other'
        and "x" not in perms[1:10]  # no execute bits anywhere
    )
    if ok:
        return True
    else:
        print(
            f"[FAIL] Insecure DB permissions: '{perms}' - 'other' permissions: '{perms[7:10] if len(perms) >= 10 else 'N/A'}'"
        )
        return False


def no_sensitive_db_on_external_storage() -> bool:
    """Ensure the app hasn't created sensitive DB files on external storage."""
    # check for NewPipe database files on external storage using ls + grep
    cmd = "adb shell 'ls -R /sdcard/' 2>/dev/null | grep -i newpipe"
    out = run_adb_command(cmd) or ""
    hits = [l.strip() for l in out.splitlines() if l.strip() and ('newpipe' in l.lower()) and (l.endswith('.db') or l.endswith('.sqlite'))]

    if hits:
        print("[FAIL] Potential sensitive DB files found on external storage:")
        for hit in hits:
            print(f"- {hit}")
        return False

    return True


def check_path_traversal_attempts(pkg: str) -> bool:
    """Check for unauthorized file access outside app sandbox."""
    # check if app has accessed files outside its sandbox
    check_paths = [
        "/system/",
        "/data/data/",
        "/proc/",
        "/dev/",
        "/data/system/",
        "/cache/",
        "/data/misc/",
    ]

    # get recent file access logs
    logcat_cmd = "adb logcat -d -s NewPipe:* | grep -i 'file\\|path\\|directory'"
    logs = run_adb_command(logcat_cmd) or ""

    for path in check_paths:
        if path in logs and pkg not in logs:  # exclude legitimate app directory access
            print(f"[FAIL] Suspicious access to: {path}")
            return False

    # also check for any files created outside app directory
    external_files_cmd = f"adb shell find /sdcard /data/local/tmp -name '*{pkg.split('.')[-1]}*' -o -name '*newpipe*' 2>/dev/null"
    external_files = run_adb_command(external_files_cmd) or ""

    if external_files.strip():
        for file in external_files.strip().splitlines():
            if file.strip() and not file.startswith("/sdcard/Android/data/" + pkg):
                print(f"[FAIL] Unauthorized file access detected: {file.strip()}")
                return False

    return True


if __name__ == "__main__":
    unauthorized_ok = test_unauthorized_db_access_fails(DB_PATH)
    authorized_ok = test_authorized_db_access_succeeds(DB_PATH)
    perms_ok = db_permissions_secure(DB_PATH)
    ext_db_ok = no_sensitive_db_on_external_storage()
    path_traversal_ok = check_path_traversal_attempts(PKG)

    if all(
        [
            unauthorized_ok,
            authorized_ok,
            perms_ok,
            ext_db_ok,
            path_traversal_ok,
        ]
    ):
        print("[PASS] Access control checks passed.")
        sys.exit(0)
    else:
        print("[FAIL] Access control checks failed.")
        sys.exit(1)
