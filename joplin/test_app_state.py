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

    before_dump = d.dump_hierarchy(compressed=True)

    clickable_elements = [
        el for el in d.xpath('//*[@clickable="true"]').all()
        if el.attrib.get('package') == app_package
    ]

    if not clickable_elements:
        print("[INFO] No clickable elements found in the app.")
        return False

    # Click the first clickable element
    el = clickable_elements[0]
    print(f"[INFO] Clicking element: {el.attrib.get('text') or el.attrib.get('resource-id')}")
    el.click()
    time.sleep(2)  
    after_dump = d.dump_hierarchy(compressed=True)

    if d(description="Back").wait(timeout=30):
        d(description="Back").click_exists(timeout=3)
    else:
        print(f"[ERROR] Could not find description: '{desc}' within {timeout}s")

    if before_dump == after_dump:
        print("[FAIL] UI did not change after click. Possibly unresponsive.")
        return False
    else:
        print("[PASS] UI changed after click. UI is responsive.")
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