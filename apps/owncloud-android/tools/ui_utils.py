import time
import os
from dotenv import load_dotenv
import logging
import uiautomator2 as u2

load_dotenv()

_LOGGER_NAME = "owncloud_ui"
logger = logging.getLogger(_LOGGER_NAME)
if not logger.handlers:
    level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    logger.setLevel(level)
    _fmt = logging.Formatter("[%(name)s] %(levelname)s %(message)s")
    _sh = logging.StreamHandler()
    _sh.setFormatter(_fmt)
    logger.addHandler(_sh)
try:
    d = u2.connect()
except Exception:
    logger.exception("Failed to connect to uiautomator2 device")
    raise

USERNAME = os.getenv("AGENT_USERNAME", "agent")
PASSWORD = os.getenv("AGENT_PASSWORD", "agentpass")
APP_PACKAGE = "com.owncloud.android"
SERVER_ADDRESS = "http://10.0.2.2:8080"
WAIT_SHORT: float = 0.2
WAIT_MED: float = 1.5
WAIT_LONG: float = 3.0
SEL = {
    "url_input": f"{APP_PACKAGE}:id/hostUrlInput",
    "refresh_desc": "Refresh connection",
    "refresh_id": f"{APP_PACKAGE}:id/embeddedCheckServerButton",
    "user": f"{APP_PACKAGE}:id/account_username",
    "pass": f"{APP_PACKAGE}:id/account_password",
    "login_btn": f"{APP_PACKAGE}:id/loginButton",
    "settings_link": f"{APP_PACKAGE}:id/settings_link",
    "first_run_skip": f"{APP_PACKAGE}:id/skip",
    "passcode_kb": f"{APP_PACKAGE}:id/numberKeyboard",
    "key1": f"{APP_PACKAGE}:id/key1",
    "key2": f"{APP_PACKAGE}:id/key2",
    "key3": f"{APP_PACKAGE}:id/key3",
    "key4": f"{APP_PACKAGE}:id/key4",
    "key5": f"{APP_PACKAGE}:id/key5",
    "key6": f"{APP_PACKAGE}:id/key6",
    "key7": f"{APP_PACKAGE}:id/key7",
    "key8": f"{APP_PACKAGE}:id/key8",
    "key9": f"{APP_PACKAGE}:id/key9",
    "key0": f"{APP_PACKAGE}:id/key0",
    "root_toolbar_avatar": f"{APP_PACKAGE}:id/root_toolbar_avatar",
    "list_root": f"{APP_PACKAGE}:id/list_root",
    "fab_button": f"{APP_PACKAGE}:id/fab_expand_menu_button",
    "bottom_nav_view": f"{APP_PACKAGE}:id/bottom_nav_view",
}


########################################
#   Page Checks
########################################
def is_on_passcode_page(timeout: float = WAIT_SHORT) -> bool:
    return d(resourceId=SEL["passcode_kb"]).exists(timeout=timeout)


def is_on_server_url_page(timeout: float = WAIT_SHORT) -> bool:
    return d(resourceId=SEL["url_input"]).exists(timeout=timeout)


def is_on_login_page(timeout: float = WAIT_SHORT) -> bool:
    return d(resourceId=SEL["login_btn"]).exists(timeout=timeout)


def is_credential_input_visible(timeout: float = WAIT_SHORT) -> bool:
    return d(resourceId=SEL["user"]).exists(timeout=timeout) and d(
        resourceId=SEL["pass"]
    ).exists(timeout=timeout)


def is_logged_in() -> bool:
    if d(resourceId=SEL["root_toolbar_avatar"]).exists(timeout=WAIT_SHORT):
        return True
    if d(resourceId=SEL["list_root"]).exists(timeout=WAIT_SHORT):
        return True
    if d(resourceId=SEL["fab_button"]).exists(timeout=WAIT_SHORT):
        return True
    if d(resourceId=SEL["bottom_nav_view"]).exists(timeout=WAIT_SHORT):
        return True
    return False


########################################
#  Helper Functions
########################################
def _handle_skip_first_run() -> None:
    """If the one-time intro screen is visible, tap SKIP. Otherwise, no-op."""
    if d(resourceId=SEL["first_run_skip"]).click_exists(timeout=WAIT_SHORT):
        time.sleep(WAIT_SHORT)
        return
    if d(text="SKIP").click_exists(timeout=WAIT_SHORT) or d(text="Skip").click_exists(
        timeout=WAIT_SHORT
    ):
        time.sleep(WAIT_SHORT)
        return


def _enter_server_url() -> bool:
    el = d(resourceId=SEL["url_input"])
    if not el.exists(timeout=WAIT_SHORT):
        return False
    el.set_text(SERVER_ADDRESS)
    time.sleep(WAIT_SHORT)
    return True


def _click_refresh_button() -> bool:
    if d(description=SEL["refresh_desc"]).click_exists(timeout=WAIT_SHORT):
        return True
    if d(resourceId=SEL["refresh_id"]).click_exists(timeout=WAIT_SHORT):
        return True
    return False


def _enter_username_and_password() -> bool:
    """Fill in username/password on ownCloud login screen and submit."""
    try:
        if d(resourceId=SEL["user"]).exists(timeout=WAIT_SHORT):
            d(resourceId=SEL["user"]).click()
            d.send_keys(USERNAME)
        else:
            logger.warning("Cannot find username field")

        if d(resourceId=SEL["pass"]).exists(timeout=WAIT_SHORT):
            d(resourceId=SEL["pass"]).click()
            d.send_keys(PASSWORD)
        else:
            logger.warning("Cannot find password field")

        if not d(resourceId=SEL["login_btn"]).click_exists(timeout=WAIT_SHORT):
            logger.warning("Cannot find login button")
            return False

        logger.info("Submitted credentials")
        time.sleep(WAIT_SHORT)
        return True
    except Exception:
        logger.exception("Error entering credentials")
        return False


def _do_login(pin: str) -> bool:
    """Perform login covering both URL-connect-first and direct login screens.

    Steps:
      - If server URL input is visible, set URL and tap Refresh.
      - If login screen is visible after first step, enter credentials and submit.
      - If passcode appears after submission, enter it. (glitch)
      - Return True only if main screen is reached.
    """
    # If we are on the server URL screen, fill and refresh
    if is_on_server_url_page():
        if not _enter_server_url():
            logger.warning("Failed to set server URL")
            return False
        if not _click_refresh_button():
            logger.warning("Refresh button not clickable")
            return False
    time.sleep(WAIT_SHORT)
    # If we can see the login form, proceed with credentials
    if is_credential_input_visible():
        if not _enter_username_and_password():
            logger.warning("Credentials input step failed")
            return False
    else:
        if is_logged_in():
            return True
    # glitch in UI. (mostly due to pushing preference file straight to app's private storage)
    if is_on_passcode_page():
        _enter_passcode(pin)
    time.sleep(WAIT_SHORT)

    return is_logged_in()


def _enter_passcode(pin: str) -> bool:
    if not is_on_passcode_page():
        return False
    logger.info("Entering passcode…")
    key_map = {
        "1": SEL["key1"],
        "2": SEL["key2"],
        "3": SEL["key3"],
        "4": SEL["key4"],
        "5": SEL["key5"],
        "6": SEL["key6"],
        "7": SEL["key7"],
        "8": SEL["key8"],
        "9": SEL["key9"],
        "0": SEL["key0"],
    }
    try:
        for ch in pin:
            rid = key_map.get(ch)
            if rid:
                d(resourceId=rid).click()
            else:
                d(text=ch).click_exists(timeout=WAIT_SHORT)
        return True
    except Exception:
        logger.exception("Failed entering passcode")
        return False

def _open_app() -> None:
    print("Opening ownCloud app...")
    d.app_start(APP_PACKAGE, use_monkey=True)
    time.sleep(WAIT_MED)


def reach_main_screen(pin: str, timeout: float) -> bool:
    """Drive the app to its main (logged-in) screen from any entry state.
    Covers:
      1) Passcode -> Login -> Main          (with passcode, have not logged in)
      2) Login -> Passcode -> Main          (glitch)
      3) Passcode -> Main                   (with passcode, but already logged in)
      4) Login -> Main                      (no passcode)
      5) Already on Main                    (no passcode and logged in)

    Args:
        - pin: The passcode to enter.
        - timeout: The maximum time to wait for the main screen.
    """
    _open_app()
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            _handle_skip_first_run()

            if is_logged_in():
                logger.info("Already logged in")
                return True

            if is_on_passcode_page():
                if not _enter_passcode(pin):
                    logger.warning("Failed to enter passcode")
                    time.sleep(WAIT_SHORT)
                continue

            # On login flow or server URL flow
            logger.info("Checking for login page")
            if is_on_login_page() or is_on_server_url_page():
                if not _do_login(pin):
                    logger.warning("do_login() did not complete. Retrying…")
                    time.sleep(WAIT_SHORT)
                continue
        except Exception:
            # Prevent loop from breaking on transient UI errors
            logger.exception("Transient error in reach_main_screen; retrying")
            time.sleep(WAIT_SHORT)

    return is_logged_in()


if __name__ == "__main__":
    try:
        ok = reach_main_screen(pin="4512", timeout=20)
        logger.info("Login flow completed: %s", ok)
    except Exception:
        logger.exception("Fatal error running UI flow")