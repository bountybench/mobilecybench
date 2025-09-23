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

d = u2.connect()


def wait_and_click_text(text, timeout=60):
    if d(text=text).wait(timeout=timeout):
        print(text, file=sys.stderr)
        d(text=text).click_exists(timeout=3)
    else:
        print(
            f"[ERROR] Could not find text: '{text}' within {timeout}s", file=sys.stderr
        )
        print(d.dump_hierarchy(), file=sys.stderr)
        exit(1)
    wait_for_ui_stable(timeout=5)


def wait_and_click_desc(desc, timeout=60):
    if d(description=desc).wait(timeout=timeout):
        print(desc, file=sys.stderr)
        d(description=desc).click_exists(timeout=3)
    else:
        print(
            f"[ERROR] Could not find description: '{desc}' within {timeout}s",
            file=sys.stderr,
        )
        print(d.dump_hierarchy(), file=sys.stderr)
        exit(1)
    wait_for_ui_stable(timeout=5)


def wait_for_ui_stable(timeout=60, interval=0.5):
    """
    Wait until the UI hierarchy stops changing.
    """
    print("Waiting for UI to stabilize", file=sys.stderr)
    prev_hierarchy = None
    start = time.time()
    stable_count = 0
    required_stable_checks = 2  # Require 2 consecutive stable checks

    while time.time() - start < timeout:
        current_hierarchy = d.dump_hierarchy(compressed=True)
        if current_hierarchy == prev_hierarchy:
            stable_count += 1
            if stable_count >= required_stable_checks:
                print(f"UI stabilized after {stable_count} consecutive checks", file=sys.stderr)
                return True
        else:
            stable_count = 0
        prev_hierarchy = current_hierarchy
        time.sleep(interval)
    print(f"UI unstable! Timed out after {timeout}s", file=sys.stderr)
    return False


wait_for_ui_stable(timeout=120, interval=1)
wait_and_click_desc("Sidebar, Show/hide the sidebar")
wait_and_click_text("Configuration")
wait_for_ui_stable(interval=5)

label = d(text="Synchronization target")
if not label.wait(timeout=30):
    print("[ERROR] Could not find 'Synchronization target'", file=sys.stderr)
    print(d.dump_hierarchy(), file=sys.stderr)
    exit(1)

dropdown = label.sibling(className="android.view.ViewGroup")
dropdown.click()
wait_for_ui_stable(timeout=5, interval=3)
wait_and_click_text("Joplin Server (Beta)")


# Wait for form to fully load after selecting Joplin Server
time.sleep(3)  # Give UI time to render form fields

# Fill Joplin Server URL
label = d(text="Joplin Server URL")
if not label.wait(timeout=30):
    print("[ERROR] Could not find Joplin Server URL label", file=sys.stderr)
    print(d.dump_hierarchy(), file=sys.stderr)
    exit(1)

edit = label.sibling(className="android.widget.EditText")
edit.click()
time.sleep(1)  # Simple wait instead of UI stabilization
edit.set_text("http://10.0.2.2:22300")  # Direct text input instead of send_keys()
d.press("enter")
time.sleep(2)

# Fill Joplin Server email
label = d(text="Joplin Server email")
if not label.wait(timeout=30):
    print("[ERROR] Could not find Joplin Server email label", file=sys.stderr)
    print(d.dump_hierarchy(), file=sys.stderr)
    exit(1)

edit = label.sibling(className="android.widget.EditText")
edit.click()
time.sleep(1)
edit.set_text(username)  # Direct text input instead of send_keys()
d.press("enter")
time.sleep(2)

# The password field might need scrolling or have different text
print("Looking for password field...", file=sys.stderr)

# First try scrolling down to make more space
d.swipe(540, 1600, 540, 800)  # Swipe up to scroll down
time.sleep(2)

# Try multiple possible password field labels
password_field = None
possible_labels = ["Joplin Server password", "Password", "password", "Server password"]

for label_text in possible_labels:
    print(f"Trying to find: '{label_text}'", file=sys.stderr)
    label = d(text=label_text)
    if label.wait(timeout=10):
        password_field = label
        print(f"Found password field with text: '{label_text}'", file=sys.stderr)
        break

if not password_field:
    print("[ERROR] Could not find any password field with expected labels", file=sys.stderr)
    print("[DEBUG] Current UI hierarchy:", file=sys.stderr)
    print(d.dump_hierarchy(), file=sys.stderr)
    exit(1)

label = password_field

edit = label.sibling(className="android.widget.EditText")
edit.click()
time.sleep(1)
edit.set_text(password)  # Direct text input instead of send_keys()
d.press("enter")
wait_for_ui_stable(timeout=5, interval=1)

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
