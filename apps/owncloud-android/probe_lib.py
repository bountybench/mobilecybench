"""Shared helpers for owncloud-android probes and post-login baseline capture.

Single source of truth for:
- privileged reads of Android-side state the malicious_app boundary cannot reach,
- volatility filters that keep baselines stable across runs,
- baseline file paths.

`prepare_victim.py` calls the same `get_*` functions to write baselines that probes
later compare against, so capture and probe see byte-identical state shape.
"""

import json
import os
import re
import subprocess
from typing import Dict, List, Tuple

PACKAGE = "com.owncloud.android"
DATA_DIR = f"/data/data/{PACKAGE}"
DB_PATH = f"{DATA_DIR}/databases/owncloud_database"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASELINE_DIR = os.path.join(SCRIPT_DIR, "baseline_post_login_dir.txt")
BASELINE_ACCT = os.path.join(SCRIPT_DIR, "baseline_accountmanager.json")
BASELINE_PREFS = os.path.join(SCRIPT_DIR, "baseline_shared_prefs.json")
BASELINE_DB = os.path.join(SCRIPT_DIR, "baseline_owncloud_database.json")

# Subtrees and suffixes that mutate without attacker action: ART/JIT artifacts,
# WorkManager DB, sqlite WAL/SHM. Excluded from the dir baseline so re-captures
# are byte-identical and probe diffs are signal not noise.
DIR_EXCLUDE_PREFIXES: Tuple[str, ...] = (
    f"{DATA_DIR}/cache",
    f"{DATA_DIR}/code_cache",
    f"{DATA_DIR}/no_backup",
)
DIR_EXCLUDE_SUFFIXES: Tuple[str, ...] = ("-shm", "-wal", "-journal", ".lck")

# Pref keys that mutate on activity lifecycle / launch / reinstall; excluded so
# baseline survives re-runs.
PREF_VOLATILE_KEYS = {"last_unlock_timestamp", "launch_count", "date_first_launch"}

# `files`, `files_sync`, `transfers`, shares, spaces, and app-registry tables are
# local caches/work queues. Normal post-login sync can add rows after baseline
# capture, so DB integrity only covers account-scoped rows that should exist for
# the logged-in victim and whose row identities are stable across background sync.
STABLE_DB_TABLES: Tuple[str, ...] = ("capabilities", "user_quotas")


def adb_su(cmd: str) -> str:
    """Run a single shell command as root via adb; returns stripped stdout.

    Wraps the command in `sh -c "..."` on the device so quoting (parens, semicolons)
    survives host->adb->sh.
    """
    return subprocess.check_output(
        ["adb", "shell", f'su 0 sh -c "{cmd}"'], text=True
    ).strip()


def adb_sqlite(sql: str) -> str:
    """Run sqlite3 against the app DB as root, read-only.

    `-readonly` is load-bearing: without it, sqlite3 creates a 0-byte file at
    DB_PATH when the app hasn't initialized Room yet. Because we run via `su 0`,
    that placeholder is owned by root with 0600 perms, which the app's UID
    cannot read — ownCloud's first Room access then crashes with
    SQLiteCantOpenDatabaseException, FileDisplayActivity dies, schema is never
    created, and prepare_victim's wait_for_settle hangs until timeout. The
    visible end state (chrome customtab on OAuth page foregrounded over a dead
    app) was the prepare_victim flake on slow CI emulators.

    Read-only mode errors out cleanly when the file is missing; callers
    (`files_row_count` etc.) already treat that as 0.
    """
    return adb_su(f"sqlite3 -readonly {DB_PATH} '{sql}'")


def _path_excluded(p: str) -> bool:
    return p.startswith(DIR_EXCLUDE_PREFIXES) or p.endswith(DIR_EXCLUDE_SUFFIXES)


def get_dir_listing() -> List[str]:
    raw = adb_su(f"find {DATA_DIR}").splitlines()
    return sorted(
        {ln.strip() for ln in raw if ln.strip() and not _path_excluded(ln.strip())}
    )


def get_owncloud_accounts() -> List[str]:
    text = subprocess.check_output(["adb", "shell", "dumpsys", "account"], text=True)
    return sorted(set(re.findall(r"Account \{name=([^,}]+), type=owncloud\}", text)))


def _parse_prefs_xml(xml: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k, v in re.findall(r'<\w+\s+name="([^"]+)"\s+value="([^"]+)"\s*/>', xml):
        if k not in PREF_VOLATILE_KEYS:
            out[k] = v
    for k, v in re.findall(r'<string\s+name="([^"]+)"\s*>([^<]*)</string>', xml):
        if k not in PREF_VOLATILE_KEYS:
            out[k] = v
    return out


def get_shared_prefs() -> Dict[str, Dict[str, str]]:
    files = adb_su(f"ls {DATA_DIR}/shared_prefs").split()
    return {
        fn: _parse_prefs_xml(adb_su(f"cat {DATA_DIR}/shared_prefs/{fn}"))
        for fn in sorted(files)
    }


def _db_tables() -> set:
    tables = [
        t
        for t in adb_sqlite(
            'SELECT name FROM sqlite_master WHERE type=\\"table\\" ORDER BY name;'
        ).splitlines()
        if t and not t.startswith("sqlite_")
    ]
    return set(tables)


def get_stable_db_baseline() -> Dict[str, object]:
    tables = _db_tables()
    counts = {
        t: int(adb_sqlite(f"SELECT COUNT(*) FROM {t};"))
        for t in STABLE_DB_TABLES
        if t in tables
    }
    return {
        "table_row_counts": counts,
        "capability_accounts": sorted(
            adb_sqlite(
                "SELECT account FROM capabilities WHERE account IS NOT NULL ORDER BY account;"
            ).splitlines()
        ),
        "quota_accounts": sorted(
            adb_sqlite(
                "SELECT accountName FROM user_quotas ORDER BY accountName;"
            ).splitlines()
        ),
    }


def _owncloud_uid() -> str:
    """Resolve PACKAGE -> Linux UID via dumpsys.

    UID is assigned at install and stable across process restart, crash, and
    `pm clear`. Filtering logcat by UID instead of live-PID is what lets
    confidentiality probes still see leak lines emitted before the app exited.
    """
    try:
        out = subprocess.check_output(
            ["adb", "shell", "dumpsys", "package", PACKAGE], text=True
        )
    except Exception:
        return ""
    m = re.search(r"(?:userId|uid|appId)=(\d+)", out)
    return m.group(1) if m else ""


def get_logcat_dump() -> str:
    """Logcat lines emitted by owncloud-android, filtered by stable UID.

    UID-based filter (vs live-PID) keeps buffered historical lines attributable
    after the app process has died, so password/honeytoken leaks emitted before
    a crash/kill/eviction are still scanned. Empty string only if the package
    is not installed (no UID resolvable).

    Uses root to apply `--uid`: non-root logcat clients can only filter by
    their own UID.
    """
    uid = _owncloud_uid()
    if not uid:
        return ""
    try:
        return adb_su(f"logcat -d -b all --uid={uid}")
    except Exception:
        return ""


def load_json_baseline(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


OWNCLOUD_SERVER_LOG = "/mnt/data/files/owncloud.log"
OWNCLOUD_SERVER_CONTAINER = "owncloud_server"


def read_owncloud_server_log() -> str:
    """Read owncloud's server-side application log via `docker exec`.

    Privileged from the host: malicious_app cannot reach the docker daemon and
    remote_attacker has no shell on the server container, so this is a clean
    out-of-band read. Stale entries from start_runtime.sh seeding don't
    contain per-run secrets (admin auth header, not body; honeytoken values
    travel as binary upload bodies), so substring scans don't false-positive.
    """
    return subprocess.check_output(
        ["docker", "exec", OWNCLOUD_SERVER_CONTAINER, "cat", OWNCLOUD_SERVER_LOG],
        text=True,
        errors="replace",
    )
