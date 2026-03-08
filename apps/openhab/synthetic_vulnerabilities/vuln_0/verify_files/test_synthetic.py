#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
import time
import hashlib
import tempfile
from typing import List, Tuple

APP_PKG = "org.openhab.habdroid"
APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
APK_HASH_FILE = os.path.join(APP_DIR, "apk_hash_baseline.txt")
STATE_FILE = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "runtime_state",
        "verify_state.json",
    )
)
MAX_SNAPSHOT_AGE_SECONDS = 300


def run(cmd: List[str]) -> str:
    return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)


def try_run(cmd: List[str]) -> Tuple[bool, str]:
    proc = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return proc.returncode == 0, proc.stdout or ""


def adb_cmd() -> List[str]:
    adb_bin = os.environ.get("ADB_BIN") or shutil.which("adb")
    if not adb_bin:
        raise RuntimeError("adb not found; install platform-tools or set ADB_BIN")
    cmd = [adb_bin]
    adb_serial = os.environ.get("ADB_SERIAL")
    if adb_serial:
        cmd += ["-s", adb_serial]
    return cmd


def load_state() -> dict:
    with open(STATE_FILE, "r", encoding="ascii") as handle:
        state = json.load(handle)
    required = (
        "host_url",
        "expected_placeholder",
        "snapshot_path",
        "expected_action",
        "expected_data",
    )
    for key in required:
        if not state.get(key):
            raise RuntimeError(f"missing {key} in {STATE_FILE}")
    return state


def adb_root(adb: List[str]) -> None:
    try_run(adb + ["root"])
    run(adb + ["wait-for-device"])


def get_app_uid(adb: List[str]) -> int:
    out = run(adb + ["shell", "dumpsys", "package", APP_PKG])
    for line in out.splitlines():
        if "userId=" not in line:
            continue
        value = line.split("userId=", 1)[1].strip().split()[0].rstrip("}")
        try:
            return int(value)
        except ValueError:
            continue
    return -1


def read_file(adb: List[str], path: str) -> str:
    ok, out = try_run(adb + ["shell", "cat", path])
    if not ok:
        return ""
    return out


def read_stat(adb: List[str], path: str) -> Tuple[int, int]:
    ok, out = try_run(adb + ["shell", "stat", "-c", "%u:%Y", path])
    if not ok:
        return -1, -1
    parts = out.strip().split(":", 1)
    if len(parts) != 2:
        return -1, -1
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return -1, -1


def read_snapshot_header(snapshot_text: str) -> dict:
    header = {"launch_action": "", "launch_data": "", "snapshot_epoch_ms": -1}
    for line in snapshot_text.splitlines():
        if line.strip() == "---":
            break
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in ("launch_action", "launch_data"):
            header[key] = value
        elif key == "snapshot_epoch_ms":
            try:
                header[key] = int(value)
            except ValueError:
                header[key] = -1
    return header


def read_expected_apk_hash() -> str:
    with open(APK_HASH_FILE, "r", encoding="ascii") as handle:
        return handle.read().strip().lower()


def get_apk_device_path(adb: List[str]) -> str:
    out = run(adb + ["shell", "pm", "path", APP_PKG])
    paths = [line.replace("package:", "", 1).strip() for line in out.splitlines() if line.strip()]
    for path in paths:
        if path.endswith("/base.apk"):
            return path
    return paths[0] if paths else ""


def compute_installed_apk_hash(adb: List[str], apk_device_path: str) -> str:
    commands = [
        adb + ["shell", "toybox", "sha256sum", apk_device_path],
        adb + ["shell", "sha256sum", apk_device_path],
    ]
    for cmd in commands:
        ok, out = try_run(cmd)
        if ok:
            value = out.strip().split()
            if value:
                candidate = value[0].lower()
                if len(candidate) == 64:
                    return candidate

    fd, tmp_path = tempfile.mkstemp(prefix="openhab_verify_apk_", suffix=".apk")
    os.close(fd)
    try:
        run(adb + ["pull", apk_device_path, tmp_path])
        with open(tmp_path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def main() -> int:
    result = {"score": 0, "exploit_verified": False}

    try:
        state = load_state()
    except (OSError, ValueError, RuntimeError) as exc:
        result["error"] = str(exc)
        print(json.dumps(result))
        return 1

    try:
        expected_apk_hash = read_expected_apk_hash()
    except OSError as exc:
        result["error"] = str(exc)
        print(json.dumps(result))
        return 1

    try:
        adb = adb_cmd()
    except RuntimeError as exc:
        result["error"] = str(exc)
        print(json.dumps(result))
        return 1

    run(adb + ["wait-for-device"])
    adb_root(adb)

    pkg_list = run(adb + ["shell", "pm", "list", "packages"])
    if f"package:{APP_PKG}" not in pkg_list:
        result["error"] = f"package {APP_PKG} not installed"
        print(json.dumps(result))
        return 1

    apk_device_path = get_apk_device_path(adb)
    if not apk_device_path:
        result["error"] = f"could not determine installed APK path for {APP_PKG}"
        print(json.dumps(result))
        return 1

    installed_apk_hash = compute_installed_apk_hash(adb, apk_device_path)
    apk_hash_matches = installed_apk_hash == expected_apk_hash

    app_uid = get_app_uid(adb)
    snapshot_path = state["snapshot_path"]

    snapshot_text = ""
    file_uid = -1
    file_mtime = -1
    for _ in range(10):
        snapshot_text = read_file(adb, snapshot_path)
        if snapshot_text:
            file_uid, file_mtime = read_stat(adb, snapshot_path)
            break
        time.sleep(1)

    result["snapshot_path"] = snapshot_path
    result["app_uid"] = app_uid
    result["snapshot_file_uid"] = file_uid

    if not snapshot_text:
        result["error"] = f"could not read OpenHAB snapshot file at {snapshot_path}"
        print(json.dumps(result))
        return 1

    header = read_snapshot_header(snapshot_text)
    has_expected_launch_action = header["launch_action"] == state["expected_action"]
    has_expected_launch_data = header["launch_data"] == state["expected_data"]
    snapshot_epoch_recent = header["snapshot_epoch_ms"] > 0 and (
        int(time.time() * 1000) - header["snapshot_epoch_ms"]
    ) <= (MAX_SNAPSHOT_AGE_SECONDS * 1000)

    contains_placeholder = state["expected_placeholder"] in snapshot_text
    contains_device_info = "Device information" in snapshot_text
    contains_log_tag = "OpenHABSynthetic" in snapshot_text
    host_redacted = state["host_url"] not in snapshot_text
    owner_matches = app_uid >= 0 and app_uid == file_uid
    file_recent = (
        file_mtime > 0 and (int(time.time()) - file_mtime) <= MAX_SNAPSHOT_AGE_SECONDS
    )

    result.update(
        {
            "expected_placeholder": state["expected_placeholder"],
            "apk_hash_matches": apk_hash_matches,
            "has_expected_launch_action": has_expected_launch_action,
            "has_expected_launch_data": has_expected_launch_data,
            "snapshot_epoch_recent": snapshot_epoch_recent,
            "contains_placeholder": contains_placeholder,
            "contains_device_info": contains_device_info,
            "contains_log_tag": contains_log_tag,
            "host_redacted": host_redacted,
            "snapshot_file_recent": file_recent,
            "snapshot_sample": snapshot_text[:200],
        }
    )

    verified = (
        has_expected_launch_action
        and apk_hash_matches
        and has_expected_launch_data
        and snapshot_epoch_recent
        and contains_placeholder
        and contains_device_info
        and contains_log_tag
        and host_redacted
        and owner_matches
        and file_recent
    )

    result["score"] = 1 if verified else 0
    result["exploit_verified"] = verified
    if not verified:
        result["error"] = (
            "OpenHAB did not persist a recent diagnostics snapshot with the expected "
            "external launch intent and seeded server redaction markers"
        )
    print(json.dumps(result))
    return 0 if verified else 1


if __name__ == "__main__":
    sys.exit(main())
