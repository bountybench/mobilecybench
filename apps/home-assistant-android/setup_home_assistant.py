import argparse
import sys
import time

import uiautomator2 as u2


def parse_args():
    parser = argparse.ArgumentParser(description="Home Assistant login script")
    parser.add_argument("--username", required=True, help="username")
    parser.add_argument(
        "--hostname",
        required=True,
        help="Host address where Home Assistant is running",
    )
    return parser.parse_args()


def wait_and_click_text(d: u2.Device, text: str, timeout: float = 30):
    if d(text=text).wait(timeout=timeout):
        d(text=text).click_exists(timeout=3)
        time.sleep(1.5)
        return True
    return False


def wait_and_click_hamburger(d: u2.Device, timeout: float = 30):
    if d(className="android.widget.ImageButton").wait(timeout=timeout):
        d(className="android.widget.ImageButton").click_exists(timeout=3)
        time.sleep(1.5)
        return True
    return False


def fill_and_submit_server_address(d: u2.Device, address: str):
    edits = list(d(className="android.widget.EditText"))
    if len(edits) >= 1:
        edits[0].click()
        time.sleep(0.2)
        edits[0].set_text("")
        edits[0].set_text(address)
        time.sleep(0.2)

    d.press("enter")
    return True


def skip_continue_dialog(d: u2.Device):
    for _ in range(5):
        if d(text="Continue").exists:
            d(text="Continue").click_exists()
            time.sleep(0.5)


def wait_login_failure_banner(d: u2.Device, timeout: float = 6.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        if d(textContains="Invalid").exists or d(text="Invalid").exists:
            return True
        time.sleep(0.2)
    return False


def logout_current_user(d: u2.Device, username: str, timeout: float = 15.0) -> bool:
    start = time.time()
    if not wait_and_click_hamburger(d, timeout=3):
        return False

    if not wait_and_click_text(d, username, timeout=3):
        return False

    if not wait_and_click_text(d, "Log out", timeout=3):
        return False

    if not wait_and_click_text(d, "Log out", timeout=3):
        return False

    while time.time() < start + timeout:
        if d(text="Welcome").exists or d(text="Continue").exists:
            return True
        time.sleep(0.3)
    return False


def main():
    args = parse_args()

    try:
        d = u2.connect()
    except Exception as e:
        print(f"Could not connect to device: {e}", file=sys.stderr)
        sys.exit(2)

    # Wait for login screen and start Home Assistant app
    d.press("home")

    pkg_name = "io.homeassistant.companion.android.minimal"

    d.app_clear(pkg_name)
    d.app_start(pkg_name)
    time.sleep(3)

    # Go back to main screen if not already there
    if d(text="Overview").wait(timeout=2):
        print("Logging out user first.")
        if not logout_current_user(d, args.username):
            print("Logout attempt failed. Please check Android device and try again.")
            sys.exit(1)
        else:
            print("Logout was successful.")
    else:
        print("Login screen detected. Proceeding with login.")

    skip_continue_dialog(d)
    wait_and_click_text(d, "Enter address manually", timeout=3)

    if not fill_and_submit_server_address(d, f"http://{args.hostname}:8123"):
        print("Could not fill and submit server address.")
        sys.exit(1)

    print("Successful run.")
    sys.exit(0)


if __name__ == "__main__":
    main()
