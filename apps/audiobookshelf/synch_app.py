import argparse
import sys
import time

import uiautomator2 as u2

parser = argparse.ArgumentParser(description="Audiobookshelf Server synchronization")
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

    while time.time() - start < timeout:
        current_hierarchy = d.dump_hierarchy(compressed=True)
        if current_hierarchy == prev_hierarchy:
            return True
        prev_hierarchy = current_hierarchy
        time.sleep(interval)
    print("UI unstable!", file=sys.stderr)
    return False


wait_for_ui_stable(timeout=120, interval=1)
wait_and_click_text("Connect")


# Fill Audiobookshelf Server URL and submit. Clicking the Submit
# button is more reliable than press("enter") — Enter does not always
# trigger the Vue form's @submit.prevent handler in the v0.10.0
# WebView, which leaves the script stuck on the server-address screen.
d(className="android.widget.EditText", instance=0).set_text("http://10.0.2.2:13378")
d(text="Submit").click()
wait_for_ui_stable(timeout=10)

# Detect URL-rejection error early. If submission failed, the server
# form re-renders and instance=0 still points at the URL field; without
# this guard, the username gets typed into the URL field and we waste
# 30s waiting for instance=1 to appear.
if d(textContains="Failed to contact server").exists:
    print(
        "[ERROR] Server URL rejected — submission failed. "
        "Audiobookshelf showed: 'Failed to contact server'.",
        file=sys.stderr,
    )
    print(d.dump_hierarchy(), file=sys.stderr)
    exit(1)

# Wait for the login form (the second EditText) to appear. This is the
# reliable indicator that we transitioned past the server-address screen.
if not d(className="android.widget.EditText", instance=1).wait(timeout=30):
    print(
        "[ERROR] Login form did not appear after URL submission "
        "(password EditText instance=1 not found within 30s)",
        file=sys.stderr,
    )
    print(d.dump_hierarchy(), file=sys.stderr)
    exit(1)

# Now safe to fill username + password.
d(className="android.widget.EditText", instance=0).set_text(username)
d(className="android.widget.EditText", instance=1).set_text(password)

wait_and_click_text("Submit")
