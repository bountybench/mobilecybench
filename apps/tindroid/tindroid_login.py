import argparse
import sys
import time

import uiautomator2 as u2


def parse_args():
    parser = argparse.ArgumentParser(description="Tindroid login script")
    parser.add_argument("--username", required=True, help="Tinode login, e.g. user_a")
    parser.add_argument("--password", required=True, help="password")
    parser.add_argument(
        "--expect",
        default="Group Chat ABC",
        help="Text expected on the chat list after successful login",
    )
    parser.add_argument(
        "--logout-after",
        action="store_true",
        help="Log out after a successful login",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print PASS/FAIL/INFO/WARN messages to stdout. ERROR messages are always printed.",
    )
    return parser.parse_args()


def wait_and_click_text(d: u2.Device, text: str, timeout: float = 30):
    if d(text=text).wait(timeout=timeout):
        d(text=text).click_exists(timeout=3)
        time.sleep(1.5)
        return True
    return False


def fill_and_submit_login(d: u2.Device, username: str, password: str):
    # Preferred: fill by labels with sibling EditText
    filled_login = False
    login_label = d(text="Login")
    if login_label.exists:
        login_edit = login_label.sibling(className="android.widget.EditText")
        if login_edit.exists:
            login_edit.click()
            time.sleep(0.3)
            login_edit.set_text("")
            d.send_keys(username)
            d.press("enter")
            time.sleep(0.3)
            filled_login = True

    filled_pw = False
    pw_label = d(text="Password")
    if pw_label.exists:
        pw_edit = pw_label.sibling(className="android.widget.EditText")
        if pw_edit.exists:
            pw_edit.click()
            time.sleep(0.3)
            pw_edit.set_text("")
            d.send_keys(password)
            d.press("enter")
            time.sleep(0.3)
            filled_pw = True

    # Fallback: use first two EditText fields on screen
    if not (filled_login and filled_pw):
        edits = list(d(className="android.widget.EditText"))
        if len(edits) >= 1 and not filled_login:
            edits[0].click()
            time.sleep(0.2)
            edits[0].set_text("")
            d.send_keys(username)
            d.press("enter")
            time.sleep(0.2)
            filled_login = True
        if len(edits) >= 2 and not filled_pw:
            edits[1].click()
            time.sleep(0.2)
            edits[1].set_text("")
            d.send_keys(password)
            d.press("enter")
            time.sleep(0.2)
            filled_pw = True

    # Submit (accept both Sign In and SIGN IN)
    if not (
        wait_and_click_text(d, "SIGN IN", timeout=3)
        or wait_and_click_text(d, "Sign In", timeout=3)
    ):
        return False
    return True


def dismiss_runtime_dialogs(d: u2.Device):
    # Best-effort close common dialogs which could block the flow
    for _ in range(3):
        if d(text="ALLOW").exists:
            d(text="ALLOW").click_exists()
            time.sleep(0.5)
        if d(text="Allow").exists:
            d(text="Allow").click_exists()
            time.sleep(0.5)
        if d(text="OK").exists:
            d(text="OK").click_exists()
            time.sleep(0.5)


def wait_login_failure_banner(d: u2.Device, timeout: float = 6.0) -> bool:
    """Detect transient login failure UI like snackbars or toasts.

    Returns True if a failure indicator is observed within timeout seconds.
    """
    start = time.time()
    # Common texts seen: "Login failed", sometimes with trailing colon or details
    texts = ["Login failed", "Login failed:", "authentication failed", "401"]

    while time.time() - start < timeout:
        # Direct text check
        for t in texts:
            if d(textContains=t).exists or d(text=t).exists:
                return True

        # Try typical Material snackbar pattern: resource id contains 'snackbar'
        try:
            if d(resourceIdMatches=".*snackbar.*").exists:
                return True
        except Exception:
            pass

        # uiautomator2 toast detection (if enabled)
        try:
            toast = d.toast.get_message(0.1)
            if toast and any(
                tok.lower() in toast.lower()
                for tok in ["login", "failed", "rejected", "401"]
            ):
                return True
        except Exception:
            pass

        time.sleep(0.2)
    return False


def logout_current_user(d: u2.Device, timeout: float = 15.0) -> bool:
    """
    Logs out a user by following a strict flow starting from the chat list screen.

    Steps (no fallbacks; only these exact targets are used):
    - Tap the toolbar overflow (content-desc "More options").
    - Tap "Settings" in the overflow menu.
    - Tap "Security" on the Settings screen.
    - Tap "LOGOUT" on the Security screen.
    - Wait until the login screen ("Tinode Chat"/"SIGN IN"/"Login") appears.

    Returns:
    - True if the login screen is detected within timeout seconds
    - False otherwise
    """
    if not d(description="More options").click_exists(timeout=3):
        return False

    if not wait_and_click_text(d, "Settings", timeout=5):
        return False

    if not wait_and_click_text(d, "Security", timeout=5):
        return False

    if not wait_and_click_text(d, "LOGOUT", timeout=5):
        return False

    if not wait_and_click_text(d, "OK", timeout=5):
        return False

    end = time.time() + timeout
    while time.time() < end:
        if (
            d(text="Tinode Chat").exists
            or d(text="SIGN IN").exists
            or d(text="Login").exists
        ):
            return True
        time.sleep(0.3)
    return False


def main():
    args = parse_args()

    try:
        d = u2.connect()
    except Exception as e:
        print(f"[ERROR] Could not connect to device: {e}", file=sys.stderr)
        sys.exit(2)

    # Wait for login screen and start Tindroid app
    d.app_start("co.tinode.tindroidx")
    time.sleep(2)

    dismiss_runtime_dialogs(d)
    # Ensure login screen is visible
    if not d(text="Tinode Chat").wait(timeout=10):
        (
            print("[WARN] Login screen not detected. Attempting to logout first.")
            if args.verbose
            else None
        )
        if not logout_current_user(d):
            print(
                "[ERROR] Logout attempt failed. Please check Android device and try again."
                if args.verbose
                else None
            )
            if args.verbose:
                print(d.dump_hierarchy())
            sys.exit(1)
        else:
            print("[INFO] Logout successful.") if args.verbose else None
    else:
        (
            print("[INFO] Login screen detected. Proceeding with login.")
            if args.verbose
            else None
        )

    if not fill_and_submit_login(d, args.username, args.password):
        print("[ERROR] Could not fill and submit login.")
        sys.exit(1)

    # Watch briefly for transient failure banners/toasts
    if wait_login_failure_banner(d, timeout=5.0):
        (
            print("❌ [FAIL] Login failed (login failed banner detected).")
            if args.verbose
            else None
        )
        sys.exit(1)

    time.sleep(1)
    hierarchy = d.dump_hierarchy()

    # Success indicator: expected topic or chat UI present
    if (args.expect and args.expect in hierarchy) or (
        "co.tinode.tindroidx:id/startNewChat" in hierarchy
    ):
        (
            print("✅ [PASS] Login successful and main chat UI detected.")
            if args.verbose
            else None
        )
        if args.logout_after:
            if logout_current_user(d):
                print("[INFO] Logout successful.") if args.verbose else None
            else:
                print("[ERROR] Logout attempt failed.") if args.verbose else None
        sys.exit(0)

    print("[ERROR] Could not positively confirm login from UI; treating as failure.")
    print(hierarchy)
    sys.exit(1)


if __name__ == "__main__":
    main()
