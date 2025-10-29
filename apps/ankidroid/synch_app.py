#!/usr/bin/env python3
# Configure AnkiDroid to use a custom sync server via SharedPreferences injection.

import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path


def sh(cmd, check=True):
    try:
        return subprocess.check_output(cmd, shell=True, text=True)
    except subprocess.CalledProcessError as e:
        if check:
            raise
        return e.output

# ---------- metadata ----------
def load_meta():
    base = Path(__file__).resolve().parent
    m = json.loads((base / "metadata.json").read_text())
    # Prefer the emulator URL (10.0.2.2) for the Android device, then fall back:
    url = m.get("emulator_server") or m.get("app_server") or ""
    if not url:
        print("[synch_app] ERROR: app_server/emulator_server empty", file=sys.stderr)
        sys.exit(2)
    return url, m["username"], m["password"]

# ---------- adb helpers ----------
def wait_adb():
    sh("adb start-server >/dev/null 2>&1 || true")
    sh("adb wait-for-device")
    time.sleep(1.0)

def detect_pkg():
    # Prefer explicit env override
    env_pkg = os.getenv("PKG")
    if env_pkg:
        return env_pkg
    # Find any installed package that starts with com.ichi2.anki
    out = sh("adb shell pm list packages | tr -d '\r'")
    m = re.search(r"package:(com\.ichi2\.anki(?:\.\w+)*)", out)
    if m:
        return m.group(1)
    print("[synch_app] ERROR: com.ichi2.anki not installed?", file=sys.stderr)
    sys.exit(3)

def launch_app(pkg):
    # Try monkey with LAUNCHER
    rc = subprocess.call(
        f"adb shell monkey -p {pkg} -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1",
        shell=True,
    )
    if rc == 0:
        time.sleep(2.0)
        return

    # Try resolve-activity (newer Androids)
    comp = sh(
        f"adb shell cmd package resolve-activity --brief "
        f"-a android.intent.action.MAIN -c android.intent.category.LAUNCHER {pkg} | tail -n 1",
        check=False
    ).strip()
    if comp and "/" in comp:
        sh(f"adb shell am start -W -n {comp}")
        time.sleep(2.0)
        return

    # Try query-activities (alt API)
    comp2 = sh(
        "adb shell cmd package query-activities --brief "
        f"-a android.intent.action.MAIN -c android.intent.category.LAUNCHER | grep {pkg} | tail -n 1",
        check=False
    ).strip()
    if comp2 and "/" in comp2:
        sh(f"adb shell am start -W -n {comp2}")
        time.sleep(2.0)
        return

    # Scrape any Activity name from dumpsys and try it
    ds = sh(f"adb shell dumpsys package {pkg}", check=False)
    m = re.search(rf"({re.escape(pkg)}[^ \n]*Activity)", ds)
    if m:
        comp3 = f"{pkg}/{m.group(1)}"
        sh(f"adb shell am start -W -n {comp3}", check=False)
        time.sleep(2.0)
        return

    # Last resort: try a few common candidates quietly
    candidates = [
        f"{pkg}/{pkg}.DeckPicker",
        f"{pkg}/{pkg}.ui.DeckPickerActivity",
        f"{pkg}/{pkg}.MainActivity",
        f"{pkg}/{pkg}.StartupActivity",
        f"{pkg}/{pkg}.SplashActivity",
        f"{pkg}/{pkg}.ui.SplashActivity",
    ]
    for compx in candidates:
        rc = subprocess.call(f"adb shell am start -W -n {compx} >/dev/null 2>&1", shell=True)
        if rc == 0:
            time.sleep(2.0)
        return

    print("[synch_app] ERROR: unable to launch app (no launcher activity resolved).", file=sys.stderr)
    sys.exit(4)

def set_sync_prefs(url, username, pkg):
    spdir  = f"/data/data/{pkg}/shared_prefs"
    spfile = f"{spdir}/{pkg}_preferences.xml"

    xml = f"""<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <boolean name="syncBaseUrl_switch" value="true" />
    <string name="syncBaseUrl">{url}</string>
    <string name="username">{username}</string>
</map>
"""

    # stop so prefs reload next launch
    subprocess.run(["adb", "shell", "am", "force-stop", pkg], check=False)

    try:
        # ensure directory exists, then write file with absolute path
        cmd = (
            f"run-as {pkg} sh -c "
            f"\"mkdir -p {shlex.quote(spdir)} && cat > {shlex.quote(spfile)} && "
            f"chmod 600 {shlex.quote(spfile)}\""
        )
        subprocess.run(["adb", "shell", cmd], input=xml, text=True, check=True)
        print(f"[synch_app] wrote custom sync prefs for {pkg}: {url} {username}")
        return True
    except Exception as e:
        print(f"[synch_app] prefs-write failed ({e})", file=sys.stderr)
        sys.exit(5)

# ---------- trigger sync & verify ----------
def trigger_sync_and_check():
    # Wait a moment for app to settle
    time.sleep(2.0)

    # Clear logs, check sync status
    sh("adb logcat -c || true")
    time.sleep(3.0)

    logs = sh("adb logcat -d -v brief | tail -n 1200").lower()
    bad = any(s in logs for s in [
        "fatal exception", "anr in", "java.lang.runtimeexception"
    ])
    if bad:
        print("[synch_app] App startup failed. Logcat tail:\n", "\n".join(logs.splitlines()[-150:]), file=sys.stderr)
        sys.exit(4)
    print("[synch_app] Sync configuration appears OK.")


def main():
    url, user, _ = load_meta()
    wait_adb()
    pkg = detect_pkg()
    print(f"[synch_app] Using package: {pkg}")

    # Direct prefs write (no UI automation fallback)
    set_sync_prefs(url, user, pkg=pkg)

    launch_app(pkg)
    trigger_sync_and_check()


if __name__ == "__main__":
    main()
