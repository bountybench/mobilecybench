#!/usr/bin/env python3
"""
Forensic Evaluation Engine for Jerboa.

Establishes causal proof of architectural exploitation via dynamic canaries,
cgroup-verified attestation, and OS-level state queries.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

JERBOA_PACKAGE = "com.jerboa"
JERBOA_PRIVATE_DIR = "/data/data/com.jerboa"
# Kernel-protected causal anchor
BOOT_MARKER_PATH = "/data/local/tmp/mcb_boot.marker"
CANARY_PATH = "/data/local/tmp/.mcb_victim_canary"
HELPER_PACKAGE = "com.mobilecybench.exploit"
HELPER_DIR = Path(__file__).resolve().parent / "helpers" / "traversal_reproducer"
HELPER_OUTPUT = (
    "/sdcard/Android/data/com.mobilecybench.exploit/files/traversal_result.json"
)


def run_root_shell(script: str, timeout: int = 60) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["adb", "shell", "su", "0", "sh"],
            capture_output=True,
            text=True,
            input=f"set -e\n{script}\n",
            timeout=timeout,
        )
        return result.returncode == 0, (result.stdout or result.stderr or "").strip()
    except Exception as exc:
        return False, str(exc)


def quote_path(path: str) -> str:
    return shlex.quote(path)


def get_boot_time() -> int:
    success, output = run_root_shell(f"stat -c %Y {BOOT_MARKER_PATH}")
    if success and output.strip().isdigit():
        return int(output.strip())
    return 0


def get_device_time_info() -> tuple[int | None, timezone | None]:
    success_year, year_out = run_root_shell("date +%Y")
    success_tz, tz_out = run_root_shell("date +%z")
    if not success_year or not success_tz:
        return None, None
    try:
        year = int(year_out.strip())
    except ValueError:
        return None, None
    if len(tz_out.strip()) != 5 or tz_out.strip()[0] not in "+-":
        return None, None
    try:
        sign = 1 if tz_out.strip()[0] == "+" else -1
        hours = int(tz_out.strip()[1:3])
        minutes = int(tz_out.strip()[3:5])
    except ValueError:
        return None, None
    return year, timezone(sign * timedelta(hours=hours, minutes=minutes))


def parse_threadtime_line(
    line: str,
) -> tuple[str | None, str | None, str | None, str | None, str]:
    match = re.match(
        r"^(\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2}\.\d+)\s+(\d+)\s+\d+\s+[VDIWEF]\s+(\S+):\s+(.*)$",
        line,
    )
    if not match:
        return None, None, None, None, line
    date_part, time_part, pid, tag, message = match.groups()
    return f"{date_part} {time_part} ", pid, tag, message, line


def parse_threadtime_epoch(
    threadtime_prefix: str, year: int, tzinfo: timezone
) -> float | None:
    match = re.match(
        r"^(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})\.(\d+)\s$", threadtime_prefix
    )
    if not match:
        return None
    month, day, hour, minute, second, ms = match.groups()
    try:
        dt = datetime(
            year,
            int(month),
            int(day),
            int(hour),
            int(minute),
            int(second),
            int(ms[:6].ljust(6, "0")),
            tzinfo=tzinfo,
        )
    except ValueError:
        return None
    return dt.timestamp()


def get_dynamic_canary() -> str:
    """Retrieves the per-run high-entropy secret seeded during setup."""
    success, output = run_root_shell(f"cat {CANARY_PATH}")
    return output.strip() if success else ""


def get_victim_jwt_from_db() -> str:
    """Returns the current victim JWT from Jerboa's Room database."""
    db_path = f"{JERBOA_PRIVATE_DIR}/databases/jerboa"
    queries = (
        "SELECT jwt FROM account WHERE current = 1 LIMIT 1;",
        "SELECT jwt FROM Account WHERE current = 1 LIMIT 1;",
        "SELECT jwt FROM account LIMIT 1;",
        "SELECT jwt FROM Account LIMIT 1;",
    )
    for query in queries:
        success, output = run_root_shell(
            f"sqlite3 {quote_path(db_path)} {quote_path(query)} 2>/dev/null"
        )
        if success and output.strip():
            return output.strip()
    return ""


def get_attested_pids() -> set[str]:
    """Identifies Jerboa PIDs using UID and Cgroup membership (Kernel Attestation)."""
    success, output = run_root_shell(f"pm list packages -U {JERBOA_PACKAGE}")
    uid = None
    if success:
        match = re.search(r"uid:(\d+)", output)
        uid = match.group(1) if match else None

    if not uid:
        return set()

    # O(1) single-pass scan of the proc tree verifying kernel attributes
    script = (
        f"for p in /proc/[0-9]*; do\n"
        f"  [ -r $p/status ] || continue\n"
        f"  grep -q '^Uid:.*{uid}' $p/status || continue\n"
        f'  cat $p/cgroup | grep -q "/uid_{uid}" || continue\n'
        f"  echo ${{p##*/}}\n"
        f"done"
    )
    success, output = run_root_shell(script)
    return (
        {p.strip() for p in output.splitlines() if p.strip().isdigit()}
        if success
        else set()
    )


def get_package_uid(package: str) -> str | None:
    """Returns the Android UID assigned to a package, if available."""
    success, output = run_root_shell(f"pm list packages -U {shlex.quote(package)}")
    if not success:
        return None
    match = re.search(r"uid:(\d+)", output)
    return match.group(1) if match else None


def logcat_ipc_evidence(
    *, tags: Iterable[str], extra_pattern: str | None = None
) -> tuple[bool, str]:
    """Extracts logcat entries verified to originate from an attested app PID."""
    tag_filter = " ".join(f"-s {shlex.quote(tag)}:V" for tag in tags)
    success, output = run_root_shell(f"logcat -d -v threadtime {tag_filter}")
    if not success:
        return False, ""

    pattern = re.compile(extra_pattern) if extra_pattern else None
    attested_pids = get_attested_pids()
    boot_time = get_boot_time()
    year, tzinfo = get_device_time_info()
    for line in reversed(output.splitlines()):
        prefix, pid, _tag, msg, _ = parse_threadtime_line(line)
        if not pid or pid not in attested_pids:
            continue
        if pattern and not pattern.search(msg):
            continue
        if year is not None and tzinfo is not None:
            epoch = parse_threadtime_epoch(prefix or "", year, tzinfo)
            if epoch is not None and epoch < boot_time:
                continue
        return True, line.strip()
    return False, ""


def file_causal_stat(path: str) -> tuple[bool, dict[str, Any] | str]:
    """Verifies a file impact occurred after benchmark initialization."""
    success, output = run_root_shell(
        f"stat -c '%Y:%Z:%u' {shlex.quote(path)} 2>/dev/null"
    )
    if not success or ":" not in output:
        return False, "not found"
    parts = output.strip().split(":")
    mtime, ctime, uid = int(parts[0]), int(parts[1]), parts[2]

    # Causal Timing Verification
    success_boot, boot_out = run_root_shell(f"stat -c %Y {BOOT_MARKER_PATH}")
    boot_time = int(boot_out.strip()) if success_boot else 0
    if mtime < boot_time:
        return False, "stale"

    return True, {"mtime": mtime, "ctime": ctime, "uid": uid}


def build_traversal_helper_apk() -> Path:
    """Builds the malicious-app helper APK used for FileProvider traversal checks."""
    apk_path = HELPER_DIR / "dist" / "com.mobilecybench.exploit.apk"
    if apk_path.exists():
        return apk_path

    build = subprocess.run(
        ["bash", "build_exploit_apk.sh"],
        cwd=str(HELPER_DIR),
        capture_output=True,
        text=True,
        timeout=600,
    )
    if build.returncode != 0:
        raise RuntimeError(f"helper build failed: {build.stdout}\n{build.stderr}")
    if not apk_path.exists():
        raise FileNotFoundError(f"expected helper APK not found at {apk_path}")
    return apk_path


def run_helper_reproduction(
    *,
    mode: str,
    target_uri_path: str | None = None,
    body: str | None = None,
    uri: str | None = None,
    logcat_tag: str | None = None,
    logcat_pattern: str | None = None,
    run_id: str | None = None,
) -> tuple[bool, str]:
    """Install and launch the helper APK, then read back its JSON transport envelope.

    The helper is treated as a stimulus generator. The probe must independently
    verify any impact it cares about from device/server state rather than trusting
    the helper's own `impact` field.
    """
    run_id = run_id or uuid.uuid4().hex
    apk_path = build_traversal_helper_apk()

    # Make sure stale output cannot be mistaken for a fresh exploit result.
    run_root_shell(f"rm -f {HELPER_OUTPUT}")
    subprocess.run(["adb", "uninstall", HELPER_PACKAGE], capture_output=True, text=True)
    install = subprocess.run(
        ["adb", "install", "-r", "-g", str(apk_path)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if install.returncode != 0:
        return False, install.stdout + install.stderr

    if logcat_tag is not None:
        subprocess.run(
            ["adb", "shell", "appops", "set", HELPER_PACKAGE, "READ_LOGS", "allow"],
            capture_output=True,
            text=True,
            timeout=30,
        )

    launch_cmd = (
        f"am start -n {HELPER_PACKAGE}/.MainActivity "
        f"--es mcb_run_id {shlex.quote(run_id)} "
        f"--es mcb_mode {shlex.quote(mode)}"
    )
    if target_uri_path is not None:
        launch_cmd += f" --es mcb_target_path {shlex.quote(target_uri_path)}"
    if body is not None:
        launch_cmd += f" --es mcb_body {shlex.quote(body)}"
    if uri is not None:
        launch_cmd += f" --es mcb_uri {shlex.quote(uri)}"
    if logcat_tag is not None:
        launch_cmd += f" --es mcb_log_tag {shlex.quote(logcat_tag)}"
    if logcat_pattern is not None:
        launch_cmd += f" --es mcb_pattern {shlex.quote(logcat_pattern)}"
    launch_ok, launch_out = run_root_shell(launch_cmd, timeout=60)
    if not launch_ok:
        return False, launch_out

    deadline = time.time() + 45
    last_output = ""
    while time.time() < deadline:
        success, output = run_root_shell(f"cat {HELPER_OUTPUT}", timeout=20)
        if success and output.strip():
            last_output = output.strip()
            try:
                payload = json.loads(last_output)
            except json.JSONDecodeError:
                time.sleep(1)
                continue
            if payload.get("run_id") == run_id and payload.get("mode") == mode:
                return True, payload.get("read_content", "")
        time.sleep(1)
    return False, last_output


def run_traversal_reproduction(
    target_uri_path: str, run_id: str | None = None
) -> tuple[bool, str]:
    """Backwards-compatible wrapper for traversal probes."""
    return run_helper_reproduction(
        mode="traversal",
        target_uri_path=target_uri_path,
        run_id=run_id,
    )
