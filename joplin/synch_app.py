import uiautomator2 as u2
import time

d = u2.connect()

def wait_and_click_text(text, timeout=600):
    if d(text=text).wait(timeout=timeout):
        d(text=text).click_exists(timeout=3)
    else:
        print(f"[ERROR] Could not find text: '{text}' within {timeout}s")
        print(d.dump_hierarchy())
    time.sleep(5)

def wait_and_click_desc(desc, timeout=600):
    if d(description=desc).wait(timeout=timeout):
        d(description=desc).click_exists(timeout=3)
    else:
        print(f"[ERROR] Could not find description: '{desc}' within {timeout}s")
        print(d.dump_hierarchy())
    time.sleep(5)

wait_and_click_desc("Sidebar, Show/hide the sidebar")
wait_and_click_text("Synchronize")
wait_and_click_text("(None)")
wait_and_click_text("Joplin Server (Beta)")

# Fill Joplin Server URL
label = d(text="Joplin Server URL")
if label.exists:
    edit = label.sibling(className="android.widget.EditText")
    edit.click()
    d.send_keys("http://10.0.2.2:22300")

# Fill Joplin Server email
label = d(text="Joplin Server email")
if label.exists:
    edit = label.sibling(className="android.widget.EditText")
    edit.click()
    d.send_keys("admin@localhost")

# Fill Joplin Server password
label = d(text="Joplin Server password")
if label.exists:
    edit = label.sibling(className="android.widget.EditText")
    edit.click()
    d.send_keys("AdminPW123")

d.press("enter")
wait_and_click_text("CHECK SYNCHRONIZATION CONFIGURATION")
time.sleep(5)
wait_and_click_desc("Back")