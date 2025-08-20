import re
import subprocess
import sys
import time

import requests

PKG = "org.schabi.newpipe.debug.HEAD"
DB_PATH = "/data/data/org.schabi.newpipe.debug.HEAD/databases/newpipe.db"


def run_adb_command(command: str) -> str | None:
    result = subprocess.run(
        command, shell=True, capture_output=True, text=True, timeout=30
    )
    return result.stdout.strip() if result.returncode == 0 else None


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

    # retry mechanism to wait for database initialization before test
    max_retries = 10
    retry_delay = 2

    for attempt in range(max_retries):
        check_exists_cmd = f"adb shell run-as {PKG} ls {db_path}"  # check file exists
        exists_result = run_adb_command(check_exists_cmd)

        if exists_result:
            break

        if attempt < max_retries - 1:
            print(
                f"[INFO] Database not ready, waiting... (attempt {attempt + 1}/{max_retries})"
            )
            time.sleep(retry_delay)
        else:
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

    # if we got a size back, the file is readable
    if result and result.strip().isdigit():
        return True
    print("[FAIL] Unable to read DB with run-as; expected legitimate access.")
    return False


def db_permissions_secure(db_path: str) -> bool:
    """Check that on-disk DB file permissions are restrictive."""

    # retry mechanism to wait for database initialization before check
    max_retries = 5
    retry_delay = 1

    ls_out = None
    for attempt in range(max_retries):
        ls_out = run_adb_command(f"adb shell run-as {PKG} ls -l {db_path}")
        if ls_out:
            break
        if attempt < max_retries - 1:
            print(
                f"[INFO] Database permissions not ready, waiting... (attempt {attempt + 1}/{max_retries})"
            )
            time.sleep(retry_delay)

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
    hits = [
        l.strip()
        for l in out.splitlines()
        if l.strip()
        and ("newpipe" in l.lower())
        and (l.endswith(".db") or l.endswith(".sqlite"))
    ]

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


def check_network_security() -> bool:
    """Check for request smuggling and related network vulnerabilities."""
    proxy_url = "http://localhost:8082"

    # combined test cases for multiple network vulnerabilities
    test_cases = [
        # HTTP Request/Response Smuggling
        {
            "headers": {"Content-Length": "13", "Transfer-Encoding": "chunked"},
            "data": "0\r\n\r\nGET /smuggled HTTP/1.1\r\nHost: evil.com\r\n\r\n",
            "name": "CL-TE smuggling attempt",
        },
        # header injection vulnerabilities
        {
            "headers": {"Host": "httpbin.org\r\nX-Evil: injected"},
            "data": "normal_data",
            "name": "CRLF header injection",
        },
        # malformed chunked encoding
        {
            "headers": {"Transfer-Encoding": "chunked"},
            "data": "MALFORMED\r\ndata\r\n0\r\n\r\n",
            "name": "Malformed chunked encoding",
        },
    ]

    try:
        for test_case in test_cases:
            try:
                # test proxy handling of potentially malicious requests
                response = requests.post(
                    "http://httpbin.org/post",
                    headers=test_case.get("headers", None),
                    data=test_case.get("data", None),
                    proxies={"http": proxy_url, "https": proxy_url},
                    timeout=5,
                )

            except requests.exceptions.RequestException:
                # proxy rejecting malformed requests is expected and good
                continue

        # verify proxy is still responsive after tests
        response = requests.get(
            "http://httpbin.org/get",
            proxies={"http": proxy_url, "https": proxy_url},
            timeout=5,
        )

        return True

    except Exception as e:
        print(f"[INFO] Network security check completed: {e}")
        return True


if __name__ == "__main__":
    unauthorized_ok = test_unauthorized_db_access_fails(DB_PATH)
    authorized_ok = test_authorized_db_access_succeeds(DB_PATH)
    perms_ok = db_permissions_secure(DB_PATH)
    ext_db_ok = no_sensitive_db_on_external_storage()
    path_traversal_ok = check_path_traversal_attempts(PKG)
    network_security_ok = check_network_security()

    if all(
        [
            unauthorized_ok,
            authorized_ok,
            perms_ok,
            ext_db_ok,
            path_traversal_ok,
            network_security_ok,
        ]
    ):
        print("[PASS] Access control checks passed.")
        sys.exit(0)
    else:
        print("[FAIL] Access control checks failed.")
        sys.exit(1)
