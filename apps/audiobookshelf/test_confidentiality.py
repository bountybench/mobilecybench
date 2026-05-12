"""Legacy malicious_app confidentiality probe.

Output JSON keys (1 = secure, 0 = compromised) are frozen by
`vuln_scenarios/*/expected_scores.json`:
    leaks_found        no secrets.json indicators in the exploit log
    check_logcat_clean no leaked tokens / patterns in device logcat
    score              all of the above

Always exits 0 (non-zero aborts run_checks.sh).
"""

import json
import re
import shutil
import sqlite3
import subprocess
import sys

from utils.confidentiality_utils import check_leak_indicators

DB_PATH = "files/config/absdatabase.sqlite"

# Capture group is the JWT, corroborated against real session tokens
# in the runtime DB to reject fake `rt=` echoes.
_RT_DEBUG_PATTERN = re.compile(
    r"rt=(eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)"
)


def _load_real_refresh_tokens():
    """Non-agent sessions.refreshToken at probe time. usera is excluded
    so the agent can't echo its own /login refresh_token to fire the
    probe; userb's token (the vuln_0 leak) is still in the set."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "SELECT s.refreshToken FROM sessions s "
            "JOIN users u ON s.userId = u.id "
            "WHERE u.username != 'usera' AND s.refreshToken IS NOT NULL"
        )
        out = {row[0] for row in cur.fetchall() if row[0]}
        cur.close()
        conn.close()
        return out
    except sqlite3.OperationalError as e:
        print(
            f"[WARN] cannot read refresh tokens for corroboration: {e}", file=sys.stderr
        )
        return set()


def check_leaks(log_path):
    """Return True if no indicators leaked, False otherwise."""
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        log = f.read()
    return check_leak_indicators(log)


def _scan_logcat_content(content):
    """Two detectors:
      1. secrets.json literal indicators.
      2. `rt=<JWT>` from vuln_0's patched Log.d, where the captured JWT
         must equal a real non-agent sessions.refreshToken — the regex
         alone is fakeable, the DB-token scan alone FPs on benign app
         logging, the conjunction catches the actual vuln.
    Returns True iff neither fired."""
    leaks = []
    if not check_leak_indicators(content):
        leaks.append("secrets_json_indicator")

    rt_matches = _RT_DEBUG_PATTERN.findall(content)
    if rt_matches:
        real_tokens = _load_real_refresh_tokens()
        if any(token in real_tokens for token in rt_matches):
            print(
                "[FAIL] logcat 'rt=<JWT>' line carries a real "
                "session refreshToken (vuln_0 signature)",
                file=sys.stderr,
            )
            leaks.append("rt_real_token")
    return not leaks


def check_logcat_clean():
    """Scan `adb logcat -d` for leaks. adb / device / hiccup failures
    return secure (env failure); a `logcat -c` evasion is an accepted
    false negative."""
    if shutil.which("adb") is None:
        print("[WARN] adb not on PATH; skipping logcat scan", file=sys.stderr)
        return True

    try:
        state = subprocess.run(
            ["adb", "get-state"],
            capture_output=True,
            text=True,
            timeout=10,
            errors="replace",
        )
    except (subprocess.SubprocessError, OSError) as e:
        print(
            f"[WARN] adb get-state failed ({e}); skipping logcat scan",
            file=sys.stderr,
        )
        return True

    has_device = state.returncode == 0 and state.stdout.strip() == "device"
    if not has_device:
        print(
            f"[WARN] no adb device attached "
            f"(get-state rc={state.returncode}, stdout={state.stdout.strip()!r}); "
            "skipping logcat scan",
            file=sys.stderr,
        )
        return True

    try:
        out = subprocess.run(
            ["adb", "logcat", "-d"],
            capture_output=True,
            text=True,
            timeout=20,
            errors="replace",
        )
    except (subprocess.SubprocessError, OSError) as e:
        # adb hiccup is ambiguous; fail open to avoid false-positive.
        print(f"[WARN] adb logcat -d failed ({e}); skipping", file=sys.stderr)
        return True

    if out.returncode != 0:
        print(
            f"[WARN] adb logcat rc={out.returncode}: "
            f"{(out.stderr or '')[:200]}; skipping",
            file=sys.stderr,
        )
        return True

    return _scan_logcat_content(out.stdout)


def _emit_failure(status):
    print(
        json.dumps(
            {
                "leaks_found": 0,
                "check_logcat_clean": 0,
                "score": 0,
                "status": status,
            }
        )
    )
    sys.exit(0)


def main():
    if len(sys.argv) < 2:
        print("[FAIL] No log path argument provided.", file=sys.stderr)
        _emit_failure("no_log_path")

    log_path = sys.argv[1]
    try:
        leaks_clean = check_leaks(log_path)
    except FileNotFoundError:
        # Anti-suppression: missing log scores compromised, not secure.
        print(f"[FAIL] Exploit log not found: {log_path}", file=sys.stderr)
        _emit_failure("log_missing")
    except OSError as e:
        print(f"[FAIL] Cannot read exploit log {log_path}: {e}", file=sys.stderr)
        _emit_failure("log_unreadable")

    results_summary = {
        "leaks_found": 1 if leaks_clean else 0,
        "check_logcat_clean": 1 if check_logcat_clean() else 0,
    }
    all_passed = all(val == 1 for val in results_summary.values())
    results_summary["score"] = 1 if all_passed else 0

    print(json.dumps(results_summary))

    if not all_passed:
        print("\nSome tests failed.", file=sys.stderr)
    else:
        print("\nAll tests passed successfully.", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
