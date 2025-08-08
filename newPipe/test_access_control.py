import re
import sys

from common import run_adb_command

PKG = "org.schabi.newpipe.debug.HEAD"
DB_PATH = "/data/data/org.schabi.newpipe.debug.HEAD/databases/newpipe.db"


def unauthorized_db_access_fails(db_path: str) -> bool:
    """Ensure the database is NOT readable without run-as (permission should be denied).

    Avoid relying on sqlite3 availability on the device by attempting to read
    a single byte directly as the shell user. Read should fail.
    """
    # Try to read as the shell user (no run-as); it should be blocked.
    out = run_adb_command(
        f"adb shell 'sh -c \"test -r {db_path} && echo READABLE || echo BLOCKED\"'"
    )
    if out and "BLOCKED" in out:
        print(
            "[PASS] Direct shell access to DB is blocked (as expected).",
            file=sys.stderr,
        )
        return True
    else:
        print(
            "[FAIL] DB was readable without run-as; unauthorized access appears possible.",
            file=sys.stderr,
        )
        return False


def authorized_db_access_succeeds(db_path: str) -> bool:
    """Ensure the database IS readable with run-as (legitimate app access).

    Don't depend on sqlite3 or specific coreutils; verify the app user can read
    the DB file via a POSIX test (test -r).
    """
    out = (
        run_adb_command(
            f"adb shell 'run-as {PKG} sh -c \"test -r {db_path} && echo READABLE || echo NOTREAD\"'"
        )
        or ""
    )
    if "READABLE" in out:
        print("[PASS] DB is readable with run-as (legitimate access).", file=sys.stderr)
        return True
    else:
        print(
            "[FAIL] Unable to read DB with run-as; expected legitimate access.",
            file=sys.stderr,
        )
        return False


def db_permissions_secure(db_path: str) -> bool:
    """Check that on-disk DB file permissions are restrictive.

    Accept typical Android modes like 600 (-rw-------) or 660 (-rw-rw----), as long as:
    - no execute bits are set, and
    - 'other' has no permissions (---).
    """
    ls_out = run_adb_command(f'adb shell "run-as {PKG} ls -l {db_path}"')
    if not ls_out:
        print("[FAIL] Could not stat DB file using run-as.", file=sys.stderr)
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
        print(
            "[PASS] DB file permissions are restrictive (no 'other' access, no exec).",
            file=sys.stderr,
        )
        return True
    else:
        print(f"[FAIL] Insecure DB permissions: '{perms}'", file=sys.stderr)
        return False


def no_exported_providers_without_permissions(pkg: str) -> bool:
    """Ensure there are no exported content providers without explicit permissions set.

    This parses dumpsys output and flags any provider with exported=true and
    missing read/write/overall permission protection.
    """
    dumpsys = run_adb_command(f"adb shell dumpsys package {pkg}") or ""

    # Heuristic: find provider blocks/lines with exported=true
    problems = []
    for line in dumpsys.splitlines():
        if "provider" in line.lower() and "exported=" in line:
            exported_match = re.search(r"exported=([a-zA-Z]+)", line)
            if exported_match and exported_match.group(1).lower() == "true":
                # Look for any permission indicators on the same line
                has_perm = any(
                    k in line
                    for k in [
                        "permission=",
                        "readPermission=",
                        "writePermission=",
                    ]
                )
                # Some dumpsys formats show permission=null when none set
                if (not has_perm) or (
                    "permission=null" in line
                    and "readPermission=" not in line
                    and "writePermission=" not in line
                ):
                    problems.append(line.strip())

    if problems:
        print("[FAIL] Exported content providers without permissions:", file=sys.stderr)
        for p in problems:
            print(f"- {p}", file=sys.stderr)
        return False

    print(
        "[PASS] No exported content providers without permissions detected.",
        file=sys.stderr,
    )
    return True


if __name__ == "__main__":
    unauthorized_ok = unauthorized_db_access_fails(DB_PATH)
    authorized_ok = authorized_db_access_succeeds(DB_PATH)
    perms_ok = db_permissions_secure(DB_PATH)
    providers_ok = no_exported_providers_without_permissions(PKG)

    all_ok = unauthorized_ok and authorized_ok and perms_ok and providers_ok
    if all_ok:
        print("[PASS] Access control checks passed.", file=sys.stderr)
        sys.exit(0)
    else:
        print("[FAIL] Access control checks failed.", file=sys.stderr)
        sys.exit(1)
