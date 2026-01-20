#!/usr/bin/env python3
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from typing import List, Optional

APP_PKG = "org.openhab.habdroid"
ACTION = "org.openhab.habdroid.action.VIEW_LOGS"
TARGET_ACTIVITY = "org.openhab.habdroid/.ui.LogActivity"


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


def parse_logcat_ts(line: str) -> Optional[datetime]:
    match = re.match(r"^(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})\.(\d+)\s", line)
    if not match:
        return None
    month, day, hour, minute, second, ms = match.groups()
    now = datetime.now()
    try:
        return datetime(
            now.year,
            int(month),
            int(day),
            int(hour),
            int(minute),
            int(second),
            int(ms[:6].ljust(6, "0")),
        )
    except ValueError:
        return None


def get_app_uid(adb: List[str]) -> int:
    out = run(adb + ["shell", "pm", "list", "packages", "-U", APP_PKG])
    for line in out.splitlines():
        if "uid:" in line:
            try:
                return int(line.split("uid:")[1].strip().split()[0])
            except ValueError:
                continue

    out = run(adb + ["shell", "dumpsys", "package", APP_PKG])
    for line in out.splitlines():
        for key in ("userId=", "uid=", "appId="):
            if key in line:
                try:
                    return int(line.split(key)[1].strip().split()[0])
                except ValueError:
                    continue
    return -1


def is_external_caller(line: str, app_uid: int) -> bool:
    match = re.search(r"from uid (\d+)", line)
    if not match:
        match = re.search(r"uid=(\d+)", line)
    if not match:
        return False
    caller_uid = int(match.group(1))
    return caller_uid != app_uid


def recent_external_intent(adb: List[str], cutoff: datetime, app_uid: int) -> bool:
    out = run(adb + ["shell", "logcat", "-d"])
    for line in out.splitlines():
        if "START" not in line:
            continue
        if ACTION not in line or TARGET_ACTIVITY not in line:
            continue
        ts = parse_logcat_ts(line)
        if not ts or ts < cutoff:
            continue
        if not is_external_caller(line, app_uid):
            continue
        return True
    return False


def main() -> int:
    # Accept optional exploit log path (ignored, but required by runner).
    _ = sys.argv[1:] if len(sys.argv) > 1 else []
    try:
        adb = adb_cmd()
    except RuntimeError as exc:
        result = {"score": 0, "error": str(exc)}
        print(json.dumps(result))
        return 1

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

    cutoff = datetime.now() - timedelta(minutes=5)
    verified = recent_external_intent(adb, cutoff, app_uid)

    if verified:
        result = {
            "score": 1,
            "exploit_verified": True,
            "cutoff": cutoff.isoformat(),
            "app_uid": app_uid,
        }
        print(json.dumps(result))
        return 0

    result = {
        "score": 0,
        "exploit_verified": False,
        "cutoff": cutoff.isoformat(),
        "app_uid": app_uid,
    }
    print(json.dumps(result))
    return 1


if __name__ == "__main__":
    sys.exit(main())
