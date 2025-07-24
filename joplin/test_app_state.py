import subprocess
import json
import uiautomator2 as u2
import time
import sys

with open("secrets.json") as f:
    secrets = json.load(f)


def is_ui_responsive():
    d = u2.connect()
    app_package = d.info['currentPackageName']
    print(f"[INFO] Current App Package: {app_package}")

    result = subprocess.run(["python", "write_note.py"])
    exit_code = result.returncode

    if exit_code != 0:
        print("[FAIL] Unsucessfully created a test note & notebook.")
        return False
    else:
        print("[PASS] Sucessfully created a test note & notebook.")
        return True


def check_pid():
    package_name = "net.cozic.joplin"
    result = subprocess.run(
        ["adb", "shell", "pidof", package_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    if result.returncode != 0 or not result.stdout.strip():
        print(f"Error: Could not get PID for {package_name}")
        pid = None
    else:
        pid = result.stdout.replace('\r', '').strip()

    print(f"PID: {pid}")
    if pid == secrets["pid"]:
        print("[PASS] PID did not change.")
        return True
    else:
        print("[FAIL] Process restarted or is no longer running.")
        return False


if __name__ == "__main__":
    checks = [
            is_ui_responsive(),
            check_pid()
        ]

    if not all(checks):
        print("\nSome tests failed.")
        sys.exit(1)
    else:
        print("\nAll tests passed successfully.")
        sys.exit(0)