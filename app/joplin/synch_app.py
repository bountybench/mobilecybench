import uiautomator2 as u2
import time
import argparse

parser = argparse.ArgumentParser(description="Joplin Server synchronization")
parser.add_argument("--username", required=True, help="email")
parser.add_argument("--password", required=True, help="password")
args = parser.parse_args()

username = args.username
password = args.password

d = u2.connect()

def wait_and_click_text(text, timeout=600):
    if d(text=text).wait(timeout=timeout):
        d(text=text).click_exists(timeout=3)
    else:
        print(f"[ERROR] Could not find text: '{text}' within {timeout}s")
        print(d.dump_hierarchy())
    time.sleep(3)

def wait_and_click_desc(desc, timeout=600):
    if d(description=desc).wait(timeout=timeout):
        d(description=desc).click_exists(timeout=3)
    else:
        print(f"[ERROR] Could not find description: '{desc}' within {timeout}s")
        print(d.dump_hierarchy())
    time.sleep(3)

def close_all_error_popups():
    while True:
        found = False
        for el in d(className="android.view.ViewGroup", clickable=True):
            try:
                bounds = el.info['bounds']
                if bounds['left'] > 900:  
                    el.click()
                    time.sleep(0.5)  
                    found = True
                    break  
            except u2.UiObjectNotFoundError:
                continue  
        if not found:
            break  


wait_and_click_desc("Sidebar, Show/hide the sidebar")
wait_and_click_text("Configuration")

label = d(text="Synchronization target")
if label.exists:
    dropdown = label.sibling(className="android.view.ViewGroup")
    dropdown.click()
    wait_and_click_text("Joplin Server (Beta)")

# Fill Joplin Server URL
label = d(text="Joplin Server URL")
if label.exists:
    edit = label.sibling(className="android.widget.EditText")
    edit.click()
    time.sleep(2)
    edit.set_text("")
    d.send_keys("http://10.0.2.2:22300")
    d.press("enter")
time.sleep(5)

# Fill Joplin Server email
label = d(text="Joplin Server email")
if label.exists:
    edit = label.sibling(className="android.widget.EditText")
    edit.click()
    time.sleep(2)
    edit.set_text("")
    d.send_keys(username)
    d.press("enter")
time.sleep(5)

# Fill Joplin Server password
label = d(text="Joplin Server password")
if label.exists:
    edit = label.sibling(className="android.widget.EditText")
    edit.click()
    time.sleep(2)
    edit.set_text("")
    d.send_keys(password)
    d.press("enter")
time.sleep(5)

wait_and_click_text("CHECK SYNCHRONIZATION CONFIGURATION")
time.sleep(5)

hierarchy = d.dump_hierarchy()
if "Error" in hierarchy:
    print("[ERROR] Found 'Error' in UI hierarchy after sync check.")
    wait_and_click_desc("Back")
    if d(text="There are unsaved changes.").exists(timeout=30):
        print("[INFO] Unsaved changes dialog detected. Discarding changes.")
        d(text="DISCARD CHANGES").click_exists(timeout=30)
        time.sleep(3)
    else:
        print("[INFO] No unsaved changes dialog appeared.")
    close_all_error_popups()
    exit(1)  
else:
    print("[INFO] No errors detected in UI hierarchy.")
    wait_and_click_desc("Back")
    exit(0)  
