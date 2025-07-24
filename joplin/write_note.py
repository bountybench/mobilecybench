import uiautomator2 as u2
import time

d = u2.connect()

def wait_and_click_text(text, timeout=600):
    if d(text=text).wait(timeout=timeout):
        d(text=text).click_exists(timeout=3)
    else:
        print(f"[ERROR] Could not find text: '{text}' within {timeout}s")
        print(d.dump_hierarchy())
        exit(1)
    wait_for_ui_stable(timeout=5)

def wait_and_click_desc(desc, timeout=600):
    if d(description=desc).wait(timeout=timeout):
        d(description=desc).click_exists(timeout=3)
    else:
        print(f"[ERROR] Could not find description: '{desc}' within {timeout}s")
        print(d.dump_hierarchy())
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

def close_all_error_popups():
    while True:
        found = False
        for el in d(className="android.view.ViewGroup", clickable=True):
            try:
                bounds = el.info['bounds']
                if bounds['left'] > 900:  
                    el.click()
                    wait_for_ui_stable(timeout=5)
                    found = True
                    break  
            except u2.UiObjectNotFoundError:
                continue  
        if not found:
            break  

def handle_popups():
    time.sleep(1)
    
    if d(textContains="Allow").exists:
        if d(textContains="Don't ask again").exists:
            d(textContains="Don't ask again").click()
        d(textContains="ALLOW").click()
        print("Allowed location access")
        return True

    elif d(textMatches="(?i)(allow|ok|yes)").exists:
        d(textMatches="(?i)(allow|ok|yes)").click()
        print("Allowed generic permission")
        return True

    elif d(textMatches="(?i)(close|dismiss|cancel|not now)").exists:
        d(textMatches="(?i)(close|dismiss|cancel|not now)").click()
        print("Dismissed generic popup")
        return True

    return False

def resolve_all_popups(timeout=10):
    end_time = time.time() + timeout
    while time.time() < end_time:
        if not handle_popups():
            break
        time.sleep(0.5)

wait_and_click_desc("Sidebar, Show/hide the sidebar")
wait_and_click_text("New Notebook")
d.send_keys("Temporary Test Notebook For App State Check")
wait_and_click_desc("Save changes")
wait_for_ui_stable()
wait_and_click_desc("Add new, collapsed")
wait_and_click_desc("New note")

resolve_all_popups() 
wait_and_click_text("Add title")
d.send_keys("Temporary Test Note For App State Check")
d.press("enter")

wait_and_click_desc("Back")
wait_and_click_desc("Back")
exit(0)