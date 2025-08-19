import argparse
import re
import sys
import time
import xml.etree.ElementTree as ET

import uiautomator2 as u2

parser = argparse.ArgumentParser(description="Joplin Server synchronization")
parser.add_argument("--username", required=True, help="email")
parser.add_argument("--password", required=True, help="password")
args = parser.parse_args()

username = args.username
password = args.password

def log_info(message: str):
    """Log informational messages"""
    if VERBOSE:
        print(f"[INFO] {message}", file=sys.stderr)

def log_error(message: str):
    """Log error messages"""
    print(f"[ERROR] {message}", file=sys.stderr)

def log_debug(message: str):
    """Log debug messages"""
    if VERBOSE:
        print(f"[DEBUG] {message}", file=sys.stderr)

try:
    d = u2.connect()
    log_info("Successfully connected to device")
except Exception as e:
    log_error(f"Failed to connect to device: {e}")
    exit(1)

def check_device_connection() -> bool:
    """Check if device is still connected and responsive"""
    try:
        d.info
        return True
    except Exception as e:
        log_error(f"Device connection lost: {e}")
        exit(1)

def wait_and_click_text(text, timeout=45):
    if d(text=text).wait(timeout=timeout):
        d(text=text).click_exists(timeout=3)
    else:
        print(
            f"[ERROR] Could not find text: '{text}' within {timeout}s", file=sys.stderr
        )
        print(d.dump_hierarchy(), file=sys.stderr)
        exit(1)
    wait_for_ui_stable(timeout=5)


def wait_and_click_desc(desc, timeout=45):
    if d(description=desc).wait(timeout=timeout):
        d(description=desc).click_exists(timeout=3)
    else:
        print(
            f"[ERROR] Could not find description: '{desc}' within {timeout}s",
            file=sys.stderr,
        )
        print(d.dump_hierarchy(), file=sys.stderr)
        exit(1)
    wait_for_ui_stable(timeout=5)


def wait_for_ui_stable(timeout=10, interval=0.5):
    """
    Wait until the UI hierarchy stops changing.
    """
    prev_hierarchy = None
    start = time.time()

    while time.time() - start < timeout:
        current_hierarchy = d.dump_hierarchy(compressed=True)
        if current_hierarchy == prev_hierarchy:
            return True
        prev_hierarchy = current_hierarchy
        time.sleep(interval)
    return False

check_device_connection()
wait_for_ui_stable(timeout=15, interval=1)
wait_and_click_desc("Sidebar, Show/hide the sidebar")
wait_and_click_text("Configuration")
wait_for_ui_stable(timeout=15, interval=1)

check_device_connection()
label = d(text="Synchronization target")
if label.exists:
    dropdown = label.sibling(className="android.view.ViewGroup")
    dropdown.click()
    wait_for_ui_stable(timeout=5, interval=3)
    wait_and_click_text("Joplin Server (Beta)")

# Fill Joplin Server URL
check_device_connection()
label = d(text="Joplin Server URL")
if label.exists:
    edit = label.sibling(className="android.widget.EditText")
    edit.click()
    wait_for_ui_stable(timeout=5)
    edit.set_text("")
    d.send_keys("http://10.0.2.2:22300")
    d.press("enter")
wait_for_ui_stable(timeout=5)

# Fill Joplin Server email
check_device_connection()
label = d(text="Joplin Server email")
if label.exists:
    edit = label.sibling(className="android.widget.EditText")
    edit.click()
    wait_for_ui_stable(timeout=5)
    edit.set_text("")
    d.send_keys(username)
    d.press("enter")
wait_for_ui_stable(timeout=5)

# Fill Joplin Server password
check_device_connection()
label = d(text="Joplin Server password")
if label.exists:
    edit = label.sibling(className="android.widget.EditText")
    edit.click()
    wait_for_ui_stable(timeout=5)
    edit.set_text("")
    d.send_keys(password)
    d.press("enter")
wait_for_ui_stable(timeout=5, interval=1)

check_device_connection()
wait_and_click_text("CHECK SYNCHRONIZATION CONFIGURATION")
wait_for_ui_stable(timeout=10, interval=3)

hierarchy = d.dump_hierarchy()
root = ET.fromstring(hierarchy)
code = 200

for node in root.iter("node"):
    text = node.attrib.get("text", "")
    match = re.search(r"Code (\d+)", text)
    if match:
        code = int(match.group(1))
        print("Found code:", code, file=sys.stderr)

print(code)

if "Error" in hierarchy:
    print("[ERROR] Found 'Error' in UI hierarchy after sync check.", file=sys.stderr)
    wait_and_click_desc("Back")
    if d(text="There are unsaved changes.").exists(timeout=30):
        print(
            "[INFO] Unsaved changes dialog detected. Discarding changes.",
            file=sys.stderr,
        )
        d(text="DISCARD CHANGES").click_exists(timeout=30)
        wait_for_ui_stable(timeout=5)
    else:
        print("[INFO] No unsaved changes dialog appeared.", file=sys.stderr)
    exit(1)
else:
    print("[INFO] No errors detected in UI hierarchy.", file=sys.stderr)
    wait_and_click_desc("Back")
    exit(0)
