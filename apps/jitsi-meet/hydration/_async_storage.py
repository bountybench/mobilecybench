"""Shared helper: host-side AsyncStorage UPSERT against a pulled RKStorage copy.

The RN AsyncStorage SQLite DB on Android lives at
`/data/data/$PACKAGE/databases/RKStorage`, table
`catalystLocalStorage(key TEXT PRIMARY KEY, value TEXT NOT NULL)`
(`react/features/mobile/polyfills/Storage.js:95-137` plus react-native-async-storage's
shipped schema). The RN polyfill prepends `@jitsi-meet/` to every key
(`react/features/mobile/polyfills/browser.js:307`).

This helper operates on a host-side copy. The orchestrator pulls the
DB once (via `adb root` + `adb pull`), every numbered script UPSERTs
against the local file, then the orchestrator pushes back. No
`run-as` (APK is not built `android:debuggable=true`), no device-side
`sqlite3` (often missing on emulator images), no nested-shell payload
escaping.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

PACKAGE = os.environ.get("MCB_PACKAGE_NAME", "org.jitsi.meet")
KEY_PREFIX = "@jitsi-meet/"
TABLE = "catalystLocalStorage"
DEVICE_DB_PATH = f"/data/data/{PACKAGE}/databases/RKStorage"


def local_db_path() -> Path:
    return Path(
        os.environ.get(
            "MCB_HYDRATE_LOCAL_DB",
            str(Path(tempfile.gettempdir()) / f"{PACKAGE}.RKStorage.hydrate"),
        )
    )


def _connect() -> sqlite3.Connection:
    p = local_db_path()
    if not p.exists():
        raise RuntimeError(
            f"local RKStorage copy missing at {p}. "
            f"setup_state.sh must call pull_db() before any per-object script."
        )
    conn = sqlite3.connect(str(p), timeout=10)
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (TABLE,),
    ).fetchone()
    if not row:
        conn.close()
        raise RuntimeError(
            f"{TABLE} table missing in {p}. AsyncStorage was not "
            f"initialized before pull. Did the bootstrap launch fail?"
        )
    return conn


def upsert_json(unprefixed_key: str, value: Any) -> int:
    """UPSERT a JSON value. Returns byte length of the serialized payload."""
    payload = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return _upsert_raw(unprefixed_key, payload)


def upsert_string(unprefixed_key: str, value: str) -> int:
    """UPSERT a plain-string value (used for the legacy 'displayname'/'email'
    direct keys that base/settings/reducer.ts:157-158 reads as a raw string,
    NOT JSON-decoded).
    """
    if not isinstance(value, str):
        raise TypeError(f"upsert_string requires str, got {type(value).__name__}")
    return _upsert_raw(unprefixed_key, value)


def _upsert_raw(unprefixed_key: str, payload: str) -> int:
    full_key = KEY_PREFIX + unprefixed_key
    with _connect() as conn:
        conn.execute(
            f"INSERT OR REPLACE INTO {TABLE}(key, value) VALUES(?, ?)",
            (full_key, payload),
        )
        conn.commit()
    return len(payload.encode("utf-8"))


def fetch_raw(unprefixed_key: str) -> str | None:
    full_key = KEY_PREFIX + unprefixed_key
    with _connect() as conn:
        row = conn.execute(
            f"SELECT value FROM {TABLE} WHERE key=?", (full_key,)
        ).fetchone()
    return row[0] if row else None


def fetch_json(unprefixed_key: str) -> Any | None:
    raw = fetch_raw(unprefixed_key)
    return None if raw is None else json.loads(raw)


def list_keys() -> list[str]:
    with _connect() as conn:
        return [r[0] for r in conn.execute(f"SELECT key FROM {TABLE}").fetchall()]


def emit_ok(object_id: str, what: str, n_bytes: int = 0) -> None:
    suffix = f" {n_bytes}" if n_bytes else ""
    print(f"OK {object_id} {what}{suffix}", flush=True)


def fail(object_id: str, why: str) -> None:
    print(f"FAIL {object_id} {why}", file=sys.stderr, flush=True)
    sys.exit(1)
