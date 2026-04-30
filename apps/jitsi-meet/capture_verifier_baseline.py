#!/usr/bin/env python3
"""
Capture verifier-owned baseline artifacts for jitsi-meet.

Intended to run during runtime setup (apps/jitsi-meet/start_runtime.sh),
*before* the agent runs.

Artifacts written under apps/jitsi-meet/verifier_artifacts/:
  - rkstorage_baseline.json (RKStorage key/value snapshot)
  - baseline_meta.json (timestamp + container list)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _run(cmd: list[str], timeout: int = 45) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=False, timeout=timeout
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_device_file(remote_path: str) -> bytes:
    # Prefer pull (used by hydration) so we don't depend on su.
    with tempfile.TemporaryDirectory() as td:
        local = Path(td) / "pulled.bin"
        pull = _run(["adb", "pull", remote_path, str(local)], timeout=60)
        if pull.returncode == 0 and local.exists():
            return local.read_bytes()

    # Fallback: exec-out cat (may not work for /data/data without root).
    ex = _run(["adb", "exec-out", "cat", remote_path], timeout=60)
    if ex.returncode == 0 and ex.stdout:
        return ex.stdout

    raise RuntimeError(
        f"failed to read {remote_path}: "
        f"pull_rc={pull.returncode} pull_stderr={(pull.stderr or b'')[:200]!r} "
        f"exec_rc={ex.returncode} exec_stderr={(ex.stderr or b'')[:200]!r}"
    )


def _extract_rows(sqlite_bytes: bytes, key_prefix: str) -> dict[str, str]:
    if not sqlite_bytes.startswith(b"SQLite format 3"):
        raise ValueError("not a sqlite3 file")

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(sqlite_bytes)
        tmp_path = tmp.name
    try:
        conn = sqlite3.connect(tmp_path)
        rows = conn.execute("SELECT key, value FROM catalystLocalStorage").fetchall()
        conn.close()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    out: dict[str, str] = {}
    for k, v in rows:
        ks = str(k)
        if key_prefix and ks.startswith(key_prefix):
            ks = ks[len(key_prefix) :]
        out[ks] = str(v)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--package", default=os.environ.get("MCB_PACKAGE_NAME", "org.jitsi.meet")
    )
    ap.add_argument("--out-dir", default="verifier_artifacts")
    ap.add_argument("--key-prefix", default="@jitsi-meet/")
    ap.add_argument("--containers", nargs="*", default=[])
    args = ap.parse_args()

    app_dir = Path(__file__).resolve().parent
    out_dir = (app_dir / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    rk_path = f"/data/data/{args.package}/databases/RKStorage"
    rk_bytes = _read_device_file(rk_path)
    rows = _extract_rows(rk_bytes, args.key_prefix)

    (out_dir / "rkstorage_baseline.json").write_text(
        json.dumps(
            {
                "captured_at": ts,
                "package": args.package,
                "sha256": _sha256_bytes(rk_bytes),
                "rows": rows,
            },
            sort_keys=True,
        )
    )
    (out_dir / "baseline_meta.json").write_text(
        json.dumps(
            {
                "captured_at": ts,
                "package": args.package,
                "containers": list(args.containers),
            },
            sort_keys=True,
        )
    )

    # Best-effort: capture a small, verifier-owned baseline container state snapshot.
    # This is not used for scoring by default; it exists to support future
    # multi-source corroboration and audit trails.
    try:
        state: dict[str, dict[str, str]] = {}
        for c in args.containers:
            if not c:
                continue
            insp = _run(
                ["docker", "inspect", "--format", "{{json .State}}", c], timeout=30
            )
            if insp.returncode == 0 and insp.stdout:
                state[c] = {
                    "state_json": insp.stdout.decode("utf-8", "replace").strip(),
                }
            else:
                state[c] = {
                    "error": (insp.stderr or b"").decode("utf-8", "replace")[:200],
                }
        (out_dir / "container_state_baseline.json").write_text(
            json.dumps({"captured_at": ts, "containers": state}, sort_keys=True)
        )
        print(
            f"[baseline] wrote {out_dir/'container_state_baseline.json'}",
            file=sys.stderr,
        )
    except Exception as e:
        print(
            f"[baseline] WARNING: container state baseline capture failed: {e}",
            file=sys.stderr,
        )

    print(f"[baseline] wrote {out_dir/'rkstorage_baseline.json'}", file=sys.stderr)
    print(f"[baseline] wrote {out_dir/'baseline_meta.json'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
