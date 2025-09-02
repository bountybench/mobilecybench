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


class IncorrectPasscodeError(Exception):
    """Raised when an incorrect passcode is detected on the passcode screen."""

    pass


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
    "passcode_error": f"{APP_PACKAGE}:id/error",
}


########################################
#   Page Checks
########################################
def is_on_passcode_page(timeout: float = WAIT_SHORT) -> bool:
    return d(resourceId=SEL["passcode_kb"]).exists(timeout=timeout)


def has_incorrect_passcode_error(timeout: float = WAIT_SHORT) -> bool:
    """Return True if the passcode screen shows an 'Incorrect passcode' error.

    Relies on a TextView with resource-id 'com.owncloud.android:id/error' and the
    text 'Incorrect passcode'. If the resource exists but text check fails, returns False.
    """
    el = d(resourceId=SEL["passcode_error"])  # com.owncloud.android:id/error
    if not el.exists(timeout=timeout):
        return False
    try:
        if d(resourceId=SEL["passcode_error"], text="Incorrect passcode").exists(
            timeout=0
        ):
            return True
    except Exception:
        return False
    return False


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


def _do_login(pin: str) -> tuple[bool, bool, bool]:
    """Perform login covering both URL-connect-first and direct login screens.

    Steps:
      - If server URL input is visible, set URL and tap Refresh.
      - If login screen is visible after first step, enter credentials and submit.
      - If passcode appears after submission, enter it. (glitch)
      - Return True only if main screen is reached.

    Returns:
        tuple[bool, bool, bool]: (success, did_enter_passcode, did_enter_credentials)
            - success: Whether login was successful
            - did_enter_passcode: Whether passcode was entered during login flow
            - did_enter_credentials: Whether username/password credentials were entered
    """
    did_enter_passcode = False
    did_enter_credentials = False

    # If we are on the server URL screen, fill and refresh
    if is_on_server_url_page():
        if not _enter_server_url():
            logger.warning("Failed to set server URL")
            return False, did_enter_passcode, did_enter_credentials
        if not _click_refresh_button():
            logger.warning("Refresh button not clickable")
            return False, did_enter_passcode, did_enter_credentials
    time.sleep(WAIT_SHORT)
    # If we can see the login form, proceed with credentials
    if is_credential_input_visible():
        did_enter_credentials = True
        if not _enter_username_and_password():
            logger.warning("Credentials input step failed")
            return False, did_enter_passcode, did_enter_credentials
    else:
        if is_logged_in():
            return True, did_enter_passcode, did_enter_credentials
    # glitch in UI. (mostly due to pushing preference file straight to app's private storage)
    if is_on_passcode_page():
        did_enter_passcode = True
        _enter_passcode(pin)
    time.sleep(WAIT_SHORT)

    return is_logged_in(), did_enter_passcode, did_enter_credentials


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
    except Exception:
        logger.exception("Failed entering passcode")
        return False

    time.sleep(WAIT_SHORT)
    if has_incorrect_passcode_error():
        logger.error("Incorrect passcode detected")
        raise IncorrectPasscodeError("Incorrect passcode")
    return True


def _close_app() -> None:
    logger.info("Closing ownCloud app...")
    d.app_stop(APP_PACKAGE)
    time.sleep(WAIT_MED)


def _open_app() -> None:
    logger.info("Opening ownCloud app...")
    d.app_start(APP_PACKAGE, use_monkey=True)
    time.sleep(WAIT_MED)


def _enter_passcode_twice(pin: str) -> bool:
    """Enter passcode twice for passcode creation/confirmation.
    Args:
        pin: The passcode to enter
    Returns:
        bool: True if both entries were successful, False otherwise
    """
    logger.info("Entering passcode for first time")
    if not _enter_passcode(pin):
        logger.error("Failed to enter passcode on first attempt")
        return False
    time.sleep(WAIT_SHORT)  # Give UI time to transition
    logger.info("Entering passcode for confirmation")
    if not _enter_passcode(pin):
        logger.error("Failed to enter passcode on confirmation")
        return False
    logger.info("Passcode entered successfully twice")
    return True


# this is not used currently but may be useful in the future
def create_passcode_in_ui(pin: str) -> bool:
    """Navigate through UI to create a passcode: Settings -> Security -> Passcode lock -> enter PIN twice.
    Args:
        pin: The passcode to set
    Returns:
        bool: True if passcode was successfully created, False otherwise
    """
    _close_app()
    _open_app()
    _handle_skip_first_run()
    logger.info("Creating passcode via UI navigation")

    # Step 1: Navigate to Settings
    if not d(resourceId=SEL["settings_link"]).click_exists(timeout=WAIT_SHORT):
        logger.error("Could not find Settings link")
        return False
    time.sleep(WAIT_SHORT)

    # Step 2: Navigate to Security section
    if not d(text="Security").click_exists(timeout=WAIT_SHORT):
        logger.error("Could not find Security option")
        return False
    time.sleep(WAIT_SHORT)

    # Step 3: Navigate to Passcode lock
    if not d(text="Passcode lock").click_exists(timeout=WAIT_SHORT):
        logger.info("Passcode lock option not visible, attempting to scroll")
        try:
            d(scrollable=True).scroll.to(text="Passcode lock")
        except Exception as e:
            logger.warning(f"Scroll failed: {e}")
        if not d(text="Passcode lock").click_exists(timeout=WAIT_MED):
            logger.error("Could not find Passcode lock option")
            return False
    time.sleep(WAIT_SHORT)

    # Step 4: Enter passcode twice
    logger.info("Entering passcode twice")
    if not _enter_passcode_twice(pin):
        logger.error("Failed to enter passcode")
        return False

    logger.info("Passcode created successfully")

    # Step 5: Navigate back to main screen
    logger.info("Navigating back to main screen")
    for attempt in range(3):  # Try up to 3 times
        if d(description="Navigate up").click_exists(timeout=WAIT_SHORT):
            time.sleep(WAIT_SHORT)
        elif (
            attempt < 2
        ):  # Only press back if Navigate up fails and we have attempts left
            d.press("back")
            time.sleep(WAIT_SHORT)

    # Verify we're back at a recognizable screen
    time.sleep(WAIT_SHORT)
    if is_logged_in() or is_on_server_url_page() or is_credential_input_visible():
        logger.info("Successfully returned to main screen")
        return True
    else:
        logger.warning("May not have returned to main screen properly")
        return True


def reach_main_screen(pin: str, timeout: float) -> tuple[bool, bool, bool]:
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

    Returns:
        tuple[bool, bool, bool]: (success, did_login, did_enter_passcode)
            - success: Whether we reached the main screen
            - did_login: Whether we entered username/password credentials during the flow
            - did_enter_passcode: Whether we entered the passcode during the flow
    """
    _close_app()
    _open_app()
    deadline = time.time() + timeout
    did_login = False
    did_enter_passcode = False

    while time.time() < deadline:
        try:
            _handle_skip_first_run()

            if is_logged_in():
                logger.info("Already logged in")
                return True, did_login, did_enter_passcode

            if is_on_passcode_page():
                did_enter_passcode = True
                if not _enter_passcode(pin):
                    logger.warning("Failed to enter passcode")
                    time.sleep(WAIT_SHORT)
                continue

            # On login flow or server URL flow
            logger.info("Checking for login page")
            if is_on_login_page() or is_on_server_url_page():
                login_result, did_enter_passcode_during_login, did_enter_credentials = (
                    _do_login(pin)
                )
                # Track if we entered credentials during this login attempt
                if did_enter_credentials:
                    did_login = True
                if did_enter_passcode_during_login:
                    did_enter_passcode = True
                if not login_result:
                    logger.warning("do_login() did not complete. Retrying…")
                    time.sleep(WAIT_SHORT)
                continue
        except IncorrectPasscodeError:
            logger.error("Incorrect passcode supplied; aborting UI flow")
            raise
        except Exception:
            # Prevent loop from breaking on transient UI errors
            logger.exception("Transient error in reach_main_screen; retrying")
            time.sleep(WAIT_SHORT)

    return is_logged_in(), did_login, did_enter_passcode


if __name__ == "__main__":
    try:
        ok, did_login, did_enter_passcode = reach_main_screen(pin="4512", timeout=20)
        logger.info("Login flow completed: %s", ok)
        logger.info("Did enter credentials: %s", did_login)
        logger.info("Did enter passcode: %s", did_enter_passcode)
    except Exception:
        logger.exception("Fatal error running UI flow")
