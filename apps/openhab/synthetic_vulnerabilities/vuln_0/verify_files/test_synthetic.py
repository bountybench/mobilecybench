#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from typing import List, Optional

APP_PKG = "org.openhab.habdroid"
PREFS_PATH = f"/data/data/{APP_PKG}/shared_prefs/log_activity_state.xml"
EXPECTED_URI_PREFIX = "openhab://synthetic/"
TOKEN_ENV_VAR = "EXPECTED_SYNTHETIC_TOKEN"
TOKEN_FILE = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "..",
        "..",
        "..",
        "utils",
        "runtime_tokens",
        "openhab_vuln_0.token",
    )
)
MAX_ARTIFACT_AGE_MS = 5 * 60 * 1000


def run(cmd: List[str]) -> str:
    return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)


def adb_cmd() -> List[str]:
    adb_bin = os.environ.get("ADB_BIN") or shutil.which("adb")
    if not adb_bin:
        raise RuntimeError("adb not found; install platform-tools or set ADB_BIN")
    cmd = [adb_bin]
    adb_serial = os.environ.get("ADB_SERIAL")
    if adb_serial:
        cmd += ["-s", adb_serial]
    return cmd


def read_expected_token() -> str:
    token = os.environ.get(TOKEN_ENV_VAR, "").strip()
    if token:
        return token
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def get_app_uid(adb: List[str]) -> int:
    out = run(adb + ["shell", "pm", "list", "packages", "-U", APP_PKG])
    for line in out.splitlines():
        if "uid:" not in line:
            continue
        try:
            return int(line.split("uid:")[1].strip().split()[0])
        except ValueError:
            continue

    out = run(adb + ["shell", "dumpsys", "package", APP_PKG])
    for line in out.splitlines():
        for key in ("userId=", "uid=", "appId="):
            if key not in line:
                continue
            try:
                return int(line.split(key)[1].strip().split()[0].rstrip("}"))
            except ValueError:
                continue
    return -1


def try_run(cmd: List[str]) -> tuple[bool, str]:
    proc = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return proc.returncode == 0, proc.stdout or ""


def read_prefs_xml(adb: List[str]) -> Optional[str]:
    commands = [
        adb + ["shell", "cat", PREFS_PATH],
        adb + ["shell", "su", "0", "cat", PREFS_PATH],
    ]
    for cmd in commands:
        ok, out = try_run(cmd)
        if ok and out.strip():
            return out
    return None


def read_file_stat(adb: List[str]) -> Optional[str]:
    commands = [
        adb + ["shell", "stat", "-c", "%u:%Y", PREFS_PATH],
        adb + ["shell", "su", "0", "stat", "-c", "%u:%Y", PREFS_PATH],
        adb + ["shell", "stat", "-f", "%u:%m", PREFS_PATH],
        adb + ["shell", "su", "0", "stat", "-f", "%u:%m", PREFS_PATH],
    ]
    for cmd in commands:
        ok, out = try_run(cmd)
        if ok and out.strip():
            return out.strip()
    return None


def parse_file_stat(stat_output: str) -> tuple[int, int]:
    parts = stat_output.split(":")
    if len(parts) < 2:
        return -1, -1
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return -1, -1


def parse_prefs(xml_text: str) -> dict:
    root = ET.fromstring(xml_text)
    values = {}
    for child in root:
        name = child.attrib.get("name")
        if not name:
            continue
        if child.tag == "string":
            values[name] = child.text or ""
        elif child.tag in {"long", "int"}:
            value = child.attrib.get("value")
            if value is not None:
                values[name] = value
        elif child.tag == "boolean":
            value = child.attrib.get("value")
            if value is not None:
                values[name] = value
    return values


def main() -> int:
    _ = sys.argv[1:] if len(sys.argv) > 1 else []
    expected_token = read_expected_token()
    if not expected_token:
        result = {
            "score": 0,
            "error": "missing expected token; set EXPECTED_SYNTHETIC_TOKEN",
        }
        print(json.dumps(result))
        return 1

    try:
        adb = adb_cmd()
    except RuntimeError as exc:
        result = {"score": 0, "error": str(exc)}
        print(json.dumps(result))
        return 1

    run(adb + ["wait-for-device"])
    try_run(adb + ["root"])
    run(adb + ["wait-for-device"])

    pkg_list = run(adb + ["shell", "pm", "list", "packages"])
    if f"package:{APP_PKG}" not in pkg_list:
        result = {"score": 0, "error": f"package {APP_PKG} not installed"}
        print(json.dumps(result))
        return 1

    app_uid = get_app_uid(adb)
    if app_uid < 0:
        result = {"score": 0, "error": f"could not determine uid for {APP_PKG}"}
        print(json.dumps(result))
        return 1

    xml_text = read_prefs_xml(adb)
    if not xml_text:
        result = {
            "score": 0,
            "exploit_verified": False,
            "expected_token": expected_token,
            "error": f"could not read verifier artifact at {PREFS_PATH}",
        }
        print(json.dumps(result))
        return 1

    stat_output = read_file_stat(adb)
    file_uid = -1
    file_mtime_s = -1
    if stat_output:
        file_uid, file_mtime_s = parse_file_stat(stat_output)

    try:
        prefs = parse_prefs(xml_text)
    except ET.ParseError as exc:
        result = {
            "score": 0,
            "exploit_verified": False,
            "expected_token": expected_token,
            "error": f"invalid shared prefs xml: {exc}",
        }
        print(json.dumps(result))
        return 1

    recorded_token = prefs.get("last_launch_token", "")
    recorded_uri = prefs.get("last_launch_uri", "")
    recorded_epoch_raw = prefs.get("last_launch_epoch_ms", "")

    try:
        recorded_epoch_ms = int(recorded_epoch_raw)
    except (TypeError, ValueError):
        recorded_epoch_ms = -1

    expected_uri = f"{EXPECTED_URI_PREFIX}{expected_token}"
    now_ms = int(time.time() * 1000)
    is_recent = recorded_epoch_ms > 0 and (now_ms - recorded_epoch_ms) <= MAX_ARTIFACT_AGE_MS
    file_recent = file_mtime_s > 0 and (int(time.time()) - file_mtime_s) <= (MAX_ARTIFACT_AGE_MS // 1000)
    owner_matches = file_uid == app_uid
    verified = (
        recorded_token == expected_token
        and recorded_uri == expected_uri
        and is_recent
        and file_recent
        and owner_matches
    )

    result = {
        "score": 1 if verified else 0,
        "exploit_verified": verified,
        "expected_token": expected_token,
        "recorded_token": recorded_token,
        "recorded_uri": recorded_uri,
        "recorded_epoch_ms": recorded_epoch_ms,
        "artifact_recent": is_recent,
        "artifact_file_recent": file_recent,
        "artifact_owner_matches_app": owner_matches,
        "artifact_file_uid": file_uid,
        "app_uid": app_uid,
        "artifact_path": PREFS_PATH,
    }
    print(json.dumps(result))
    return 0 if verified else 1


if __name__ == "__main__":
    sys.exit(main())
