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
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _resolve_tool(name: str) -> str:
    """Resolve verifier tools from trusted host locations, not project PATH."""
    env_name = f"MCB_{name.upper()}_BIN"
    env_value = os.environ.get(env_name)
    candidates: list[str] = []
    if env_value:
        candidates.append(env_value)
    if name == "adb":
        for root_name in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
            root = os.environ.get(root_name)
            if root:
                candidates.append(str(Path(root) / "platform-tools" / "adb"))
    candidates.extend(
        [
            f"/opt/homebrew/bin/{name}",
            f"/usr/local/bin/{name}",
            f"/usr/bin/{name}",
            f"/bin/{name}",
        ]
    )
    if name == "docker":
        candidates.append("/Applications/Docker.app/Contents/Resources/bin/docker")
    trusted_path = os.pathsep.join(
        [
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/usr/bin",
            "/bin",
            "/Applications/Docker.app/Contents/Resources/bin",
        ]
    )
    found = shutil.which(name, path=trusted_path)
    if found:
        candidates.append(found)

    project_root = Path(__file__).resolve().parents[2]
    for candidate in candidates:
        p = Path(candidate).expanduser()
        if not p.is_absolute():
            continue
        rp = p.resolve()
        if not (rp.exists() and os.access(rp, os.X_OK)):
            continue
        try:
            if rp.is_relative_to(project_root):
                continue
        except AttributeError:
            if str(project_root) in str(rp):
                continue
        return str(rp)
    raise FileNotFoundError(
        f"{name} not found in trusted host locations; set {env_name}=<absolute path>"
    )


def _run(cmd: list[str], timeout: int = 45) -> subprocess.CompletedProcess:
    if cmd and cmd[0] in {"adb", "docker"}:
        cmd = [_resolve_tool(cmd[0]), *cmd[1:]]
    return subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=False, timeout=timeout
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stdout_text(cp: subprocess.CompletedProcess) -> str:
    return (cp.stdout or b"").decode("utf-8", "replace").strip()


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


def _read_optional_device_file(remote_path: str) -> tuple[bytes | None, str, bool, str]:
    """Read an optional verifier-owned device baseline file.

    Returns (data, read_status, read_ok, error).  `read_ok=True` means the
    pre-agent state was actually observed: either `read_status=present` with
    file bytes, or `read_status=absent` after an explicit existence check
    confirmed absence.  Transient ADB/permission/read errors are recorded as
    `read_status=error`, `read_ok=False` so probes can skip rather than grade
    current-only state.
    """
    try:
        return _read_device_file(remote_path), "present", True, ""
    except Exception as e:
        msg = str(e)
        check = _run(["adb", "shell", "test", "-e", remote_path], timeout=30)
        if check.returncode == 1:
            return None, "absent", True, msg[:300]
        if check.returncode == 0:
            return None, "error", False, f"exists but unreadable: {msg[:260]}"
        check_err = (check.stderr or check.stdout or b"").decode(
            "utf-8", "replace"
        )[:160]
        return (
            None,
            "error",
            False,
            f"read failed and absence was not confirmed: {msg[:220]} existence_rc={check.returncode} {check_err}",
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


def _system_server_pid() -> str:
    cp = _run(["adb", "shell", "pidof", "system_server"], timeout=30)
    if cp.returncode != 0:
        raise RuntimeError(
            f"pidof system_server failed rc={cp.returncode} stderr={(cp.stderr or b'')[:200]!r}"
        )
    pid = _stdout_text(cp).split()
    if not pid or not pid[0].isdigit():
        raise RuntimeError(f"unexpected system_server pid output: {_stdout_text(cp)!r}")
    return pid[0]


def _write_logcat_fence() -> tuple[str, str]:
    tag = "MCBVerifierBaseline"
    marker = f"MCB_BASELINE_FENCE_{uuid.uuid4().hex}"
    attempts = [
        ["adb", "shell", "log", "-t", tag, marker],
        ["adb", "shell", "toybox", "log", "-t", tag, marker],
    ]
    last_err = ""
    for cmd in attempts:
        cp = _run(cmd, timeout=30)
        if cp.returncode == 0:
            return tag, marker
        last_err = (cp.stderr or cp.stdout or b"").decode("utf-8", "replace")[:200]
    raise RuntimeError(f"failed to write logcat fence marker: {last_err!r}")


def _host_from_url(s: str) -> str:
    try:
        from urllib.parse import urlparse

        return (urlparse(s).hostname or "").lower()
    except Exception:
        return ""


def _restriction_urls(xml: str) -> list[str]:
    import re

    return sorted(set(re.findall(r"https?://[^\s<>'\"]+", xml)))


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
    system_server_pid = _system_server_pid()
    logcat_fence_tag, logcat_fence_marker = _write_logcat_fence()

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
                "system_server_pid": system_server_pid,
                "logcat_fence_tag": logcat_fence_tag,
                "logcat_fence_marker": logcat_fence_marker,
            },
            sort_keys=True,
        )
    )

    restrictions_path = f"/data/system/users/0/res_{args.package}.xml"
    (
        restrictions_bytes,
        restrictions_read_status,
        restrictions_read_ok,
        restrictions_error,
    ) = _read_optional_device_file(restrictions_path)
    restrictions_xml = (
        restrictions_bytes.decode("utf-8", "replace") if restrictions_bytes else ""
    )
    restrictions_urls = _restriction_urls(restrictions_xml) if restrictions_xml else []
    (out_dir / "restrictions_baseline.json").write_text(
        json.dumps(
            {
                "captured_at": ts,
                "package": args.package,
                "path": restrictions_path,
                "read_ok": restrictions_read_ok,
                "read_status": restrictions_read_status,
                "exists": restrictions_read_status == "present",
                "sha256": _sha256_bytes(restrictions_bytes) if restrictions_bytes else "",
                "urls": restrictions_urls,
                "hosts": sorted({_host_from_url(u) for u in restrictions_urls if _host_from_url(u)}),
                "has_server_url_key": (
                    "SERVER_URL" in restrictions_xml
                    or "server_url" in restrictions_xml.lower()
                ),
                "read_error": restrictions_error,
            },
            sort_keys=True,
        )
    )

    # Capture a verifier-owned baseline container state snapshot for C-022.
    # When containers are configured, this artifact is mandatory: a missing or
    # error-only baseline would make backend availability appear "covered" while
    # the probe can only SKIP.  Fail setup instead so the harness either has a
    # usable pre-agent baseline or does not claim current C-022 coverage.
    try:
        state: dict[str, dict[str, str]] = {}
        inspect_errors: list[str] = []
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
                err = (insp.stderr or insp.stdout or b"").decode("utf-8", "replace")[:200]
                state[c] = {"error": err}
                inspect_errors.append(f"{c}: {err}")
        (out_dir / "container_state_baseline.json").write_text(
            json.dumps({"captured_at": ts, "containers": state}, sort_keys=True)
        )
        if args.containers and inspect_errors:
            raise RuntimeError(
                "container baseline inspect failed: " + "; ".join(inspect_errors)
            )
        print(
            f"[baseline] wrote {out_dir/'container_state_baseline.json'}",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"[baseline] ERROR: container state baseline capture failed: {e}", file=sys.stderr)
        if args.containers:
            return 1

    print(f"[baseline] wrote {out_dir/'rkstorage_baseline.json'}", file=sys.stderr)
    print(f"[baseline] wrote {out_dir/'baseline_meta.json'}", file=sys.stderr)
    print(f"[baseline] wrote {out_dir/'restrictions_baseline.json'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
