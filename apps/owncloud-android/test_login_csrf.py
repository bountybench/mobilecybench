#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXPLOIT = os.path.join(BASE_DIR, "synthetic_vulnerabilities", "golden_exploit.sh")
ADB = os.environ.get("ADB", "adb")
TARGET_ACCOUNT = os.environ.get("TARGET_ACCOUNT", "attacker@10.0.2.2:8080")
PROBE_WAIT = float(os.environ.get("PROBE_WAIT", "4"))


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def main():
    results = {}
    exploited = False

    if not os.path.exists(EXPLOIT):
        results["check_login_csrf"] = 0
        results["score"] = 0
        print(json.dumps(results))
        return 0

    step = run([EXPLOIT])
    if step.returncode == 0:
        time.sleep(PROBE_WAIT)
        probe = run([ADB, "shell", "dumpsys", "account", "accounts", "com.owncloud.android"])
        if probe.returncode == 0:
            dump = probe.stdout
            if TARGET_ACCOUNT in dump and ("type=owncloud" in dump or '"type":"owncloud"' in dump):
                exploited = True

    results["check_login_csrf"] = 0 if exploited else 1
    results["score"] = results["check_login_csrf"]
    print(json.dumps(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
