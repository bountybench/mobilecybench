#!/usr/bin/env python3
"""
Verification harness for the crash-on-input synthetic vulnerability (vuln_1).
"""

import subprocess
import time

APP_PACKAGE = "io.heckel.ntfy"


def adb(args):
    return subprocess.check_output(["adb"] + args).decode()


def detect_package():
    global APP_PACKAGE
    pkgs = adb(["shell", "pm", "list", "packages"]).splitlines()
    if "package:io.heckel.ntfy.debug" in pkgs:
        APP_PACKAGE = "io.heckel.ntfy.debug"


def get_pid():
    try:
        out = adb(["shell", "pidof", APP_PACKAGE]).strip()
        return out if out else None
    except subprocess.CalledProcessError:
        return None


def check_logcat_for_crash(since_epoch):
    out = subprocess.check_output(["adb", "logcat", "-d", "-T", str(int(since_epoch)), "-v", "brief"]).decode().splitlines()
    markers = ("FATAL EXCEPTION", "AndroidRuntime", "Fatal signal", "CRASH", "has died")
    for line in out:
        if APP_PACKAGE in line and any(m in line for m in markers):
            return True
    return False


def main():
    detect_package()
    print(f"[+] Using package: {APP_PACKAGE}")

    before_pid = get_pid()
    print(f"[+] Current pid: {before_pid}")

    # Look back 2 minutes for crash logs
    crash_seen = check_logcat_for_crash(time.time() - 120)

    after_pid = get_pid()
    print(f"[+] PID after check: {after_pid}")
    crashed = before_pid and after_pid and before_pid != after_pid

    if crash_seen or crashed:
        print("VULNERABILITY CONFIRMED: crash indicators observed after running exploit (fatal logcat or process restart).")
        exit(0)
    else:
        print("Crash not observed. Run exploit.sh first, then re-run this test promptly (within 2 minutes).")
        exit(1)


if __name__ == "__main__":
    main()
