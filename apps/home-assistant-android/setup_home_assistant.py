import argparse
import sys
import time

import uiautomator2 as u2

try:
    from selenium.webdriver.common.by import By  # type: ignore
    from selenium.common.exceptions import NoSuchElementException, WebDriverException  # type: ignore

    _SELENIUM_AVAILABLE = True
except Exception:  # ImportError or other
    _SELENIUM_AVAILABLE = False

    class By:  # minimal shim for type hints
        CSS_SELECTOR = "css selector"
        TAG_NAME = "tag name"

    class NoSuchElementException(Exception):
        pass

    class WebDriverException(Exception):
        pass


def parse_args():
    parser = argparse.ArgumentParser(description="Home Assistant login script")
    parser.add_argument("--username", required=True, help="username")
    parser.add_argument("--password", required=True, help="password")
    parser.add_argument(
        "--logout-after",
        action="store_true",
        help="Log out after a successful login",
    )
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

    d(className="android.view.View", clickable=True).click()
    return True


def _switch_to_webview(d: u2.Device, wait: float = 15.0):
    """Attempt to switch Selenium driver context from native to first WEBVIEW.* context.

    Returns the switched driver on success, else None.
    """
    drv = d.driver
    deadline = time.time() + wait
    last_contexts = []
    while time.time() < deadline:
        try:
            ctxs = drv.contexts
        except Exception:
            ctxs = []
        last_contexts = ctxs
        webviews = [c for c in ctxs if c.startswith("WEBVIEW")]
        if webviews:
            try:
                drv.switch_to.context(webviews[0])
                return drv
            except WebDriverException:
                pass
        time.sleep(0.5)
    print(f"No WEBVIEW context discovered (contexts observed: {last_contexts})")
    return None


def fill_and_submit_login(d: u2.Device, username: str, password: str) -> bool:
    """Fill username & password on the Home Assistant login screen.

    The login form is presented inside a WebView. We try WebView automation first;
    if that fails, fall back to native EditText heuristic. Returns True on success.
    """
    # 1. Try switching to WebView context
    drv = _switch_to_webview(d)
    if drv:
        selectors = [
            # (username_selector, password_selector, submit_selector)
            (
                "input[name='username']",
                "input[name='password']",
                "button[type='submit']",
            ),
            ("input[type='email']", "input[type='password']", "button[type='submit']"),
            ("#username", "#password", "button[type='submit']"),
        ]
        for u_sel, p_sel, btn_sel in selectors:
            try:
                u_el = drv.find_element(By.CSS_SELECTOR, u_sel)
                p_el = drv.find_element(By.CSS_SELECTOR, p_sel)
                # Clear & send keys (some HA builds may block clear(); JS fallback used)
                try:
                    u_el.clear()
                    p_el.clear()
                except Exception:
                    pass
                drv.execute_script("arguments[0].value = arguments[1];", u_el, username)
                drv.execute_script("arguments[0].value = arguments[1];", p_el, password)
                # Click submit
                try:
                    btn = drv.find_element(By.CSS_SELECTOR, btn_sel)
                    btn.click()
                except NoSuchElementException:
                    # fallback: first button element
                    try:
                        drv.find_element(By.TAG_NAME, "button").click()
                    except Exception:
                        pass
                time.sleep(2)
                return True
            except NoSuchElementException:
                continue
            except WebDriverException as e:
                print(f"WebView interaction failed with {e}. Trying next selector.")
        print(
            "Could not locate login form elements in WebView; falling back to native strategy."
        )

    # 2. Fallback: native view (less reliable if WebView is used)
    edits = list(d(classNameMatches=".*EditText"))
    if not edits:
        return False
    try:
        edits[0].click()
        time.sleep(0.2)
        edits[0].set_text("")
        edits[0].set_text(username)
        time.sleep(0.2)
        if len(edits) > 1:
            edits[1].click()
            time.sleep(0.2)
            edits[1].set_text("")
            edits[1].set_text(password)
            time.sleep(0.2)
        # Attempt generic submit: look for any clickable view with text 'Log in'
        for candidate_text in ("Log in", "Login", "Sign in"):
            if d(text=candidate_text).exists:
                d(text=candidate_text).click_exists(timeout=2)
                break
        time.sleep(2)
        return True
    except Exception as e:
        print(f"Native fallback failed: {e}")
        return False


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

    if not fill_and_submit_login(d, args.username, args.password):
        print("Could not fill and submit login. Was the account already made?")
        sys.exit(1)

    skip_continue_dialog(d)

    sys.exit(1)


if __name__ == "__main__":
    main()
