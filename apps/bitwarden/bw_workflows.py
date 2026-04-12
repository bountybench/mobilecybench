"""
Bitwarden-specific UI workflows built on top of generic ui_utils primitives.

These functions orchestrate common Bitwarden flows such as initial setup,
account creation, cipher creation, logging out, and attempting login.
"""

import logging
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote

# Absolute imports to prevent E402
from utils.ui_utils import (
    click_then_expect,
    wait_and_click,
    wait_and_set_text,
    wait_for_ui_stable,
)  # noqa: E402

from .util import BITWARDEN_PKG, SERVER_URL  # noqa: E402

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
logger = logging.getLogger("mobilecybench.bitwarden.workflows")
logger.setLevel("INFO")
_handler = logging.StreamHandler(stream=sys.stderr)
_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logger.handlers[:] = [_handler]
logger.propagate = False

SHORT_WAIT = 5
NETWORK_WAIT = 30  # network-bound operations (TLS + server round-trip on emulator)


def _resource_matches(resource_id: str | None, target: str) -> bool:
    return bool(resource_id) and (
        resource_id == target or resource_id.endswith(f"/{target}")
    )


def _parse_bounds_center(bounds: str | None) -> tuple[int, int] | None:
    if not bounds:
        return None
    match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
    if not match:
        return None
    x1, y1, x2, y2 = map(int, match.groups())
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def _dump_ui_root(d) -> ET.Element | None:
    try:
        return ET.fromstring(d.dump_hierarchy())
    except Exception as exc:
        logger.warning("Failed to parse UI hierarchy: %s", exc)
        return None


def _iter_account_cells(root: ET.Element):
    for node in root.iter():
        if _resource_matches(node.attrib.get("resource-id"), "AccountCell"):
            yield node


def _descendant_text(node: ET.Element, target_resource_id: str) -> str | None:
    for desc in node.iter():
        if _resource_matches(desc.attrib.get("resource-id"), target_resource_id):
            text = desc.attrib.get("text")
            if text:
                return text
    return None


def _has_descendant_resource(node: ET.Element, target_resource_id: str) -> bool:
    return any(
        _resource_matches(desc.attrib.get("resource-id"), target_resource_id)
        for desc in node.iter()
    )


def _find_account_cell_center(d, email: str) -> tuple[int, int] | None:
    root = _dump_ui_root(d)
    if root is None:
        return None

    for cell in _iter_account_cells(root):
        if _descendant_text(cell, "AccountEmailLabel") == email:
            return _parse_bounds_center(cell.attrib.get("bounds"))
    return None


def _find_active_account_email(d) -> str | None:
    root = _dump_ui_root(d)
    if root is None:
        return None

    for cell in _iter_account_cells(root):
        if _has_descendant_resource(cell, "ActiveVaultIcon"):
            return _descendant_text(cell, "AccountEmailLabel")
    return None


def _dismiss_alert_popup(d, timeout: float = 1.0) -> bool:
    alert = d(resourceId="AlertPopup")
    accept = d(resourceId="AcceptAlertButton")
    if alert.exists(timeout=timeout) and accept.exists(timeout=timeout):
        logger.info("Dismissing Bitwarden alert popup.")
        wait_and_click(d, accept)
        return True
    return False


def _dismiss_common_popups(d, max_rounds: int = 4) -> None:
    for _ in range(max_rounds):
        if _dismiss_alert_popup(d):
            wait_for_ui_stable(d, timeout=SHORT_WAIT)
            continue
        break


def _scroll_until_visible(d, element, max_swipes: int = 4) -> bool:
    if element.exists:
        return True

    for _ in range(max_swipes):
        try:
            scroller = d(scrollable=True)
            if scroller.exists:
                scroller.scroll.vert.forward(steps=30)
            else:
                d.swipe_ext("up", scale=0.6)
        except Exception:
            try:
                d.swipe_ext("up", scale=0.6)
            except Exception:
                return element.exists
        wait_for_ui_stable(d, timeout=SHORT_WAIT)
        if element.exists:
            return True

    return element.exists


def _is_start_registration_screen(d) -> bool:
    return (
        d(resourceId="EmailAddressEntry").exists
        and d(resourceId="NameEntry").exists
        and d(resourceId="ContinueButton").exists
    )


def _is_landing_screen(d) -> bool:
    # A LandingScreen should have an email field and either a Create Account label or the Region/Environment selector.
    return d(resourceId="EmailAddressEntry").exists and (
        d(resourceId="CreateAccountLabel").exists
        or d(resourceId="RegionSelectorDropdown").exists
        or d(resourceId="ContinueButton").exists
    )


def _is_create_account_screen(d) -> bool:
    return (
        d(resourceId="EmailAddressEntry").exists
        and d(resourceId="MasterPasswordEntry").exists
        and d(resourceId="ConfirmMasterPasswordEntry").exists
        and d(resourceId="SubmitButton").exists
    )


def _is_login_screen(d) -> bool:
    return (
        d(resourceId="MasterPasswordEntry").exists
        and d(resourceId="LogInWithMasterPasswordButton").exists
        and d(resourceId="LoggingInAsLabel").exists
        and d(resourceId="NotYouLabel").exists
    )


def _is_vault_unlock_screen(d) -> bool:
    return (
        d(resourceId="MasterPasswordEntry").exists
        and d(resourceId="UnlockVaultButton").exists
        and d(resourceId="UserAndEnvironmentDataLabel").exists
    )


def _open_account_switcher(d, expected_account_email: str | None = None) -> bool:
    account_button = d(resourceId="CurrentActiveAccount")
    if not account_button.exists:
        account_button = d(description="Account")
    if not account_button.exists:
        return False

    def switcher_visible() -> bool:
        if expected_account_email:
            return d(text=expected_account_email).exists
        return (
            d(resourceId="AccountListView").exists
            or d(resourceId="AddAccountButton").exists
            or d(resourceId="AccountEmailLabel").exists
        )

    return click_then_expect(d, account_button, switcher_visible, timeout=SHORT_WAIT)


def _show_account_actions(d, email: str) -> bool:
    if not _open_account_switcher(d, expected_account_email=email):
        return False

    center = _find_account_cell_center(d, email)
    if center is None:
        logger.warning("Could not locate AccountCell for %s.", email)
        return False

    try:
        x, y = center
        d.shell(f"input swipe {x} {y} {x} {y} 800")
    except Exception as exc:
        logger.warning("Failed to long-click AccountCell for %s: %s", email, exc)
        return False

    time.sleep(1)
    return (
        d(text="Log out").exists
        or d(text="Lock").exists
        or d(text="Remove account").exists
    )


def _logout_via_account_actions(d, email: str) -> bool:
    if not _show_account_actions(d, email):
        return False

    logout_option = d(text="Log out")
    if not logout_option.exists:
        return False

    if not click_then_expect(d, logout_option, d(text="Yes"), timeout=SHORT_WAIT):
        return False

    return click_then_expect(
        d,
        d(text="Yes"),
        lambda: d(resourceId="EmailAddressEntry").exists
        or d(resourceId="MasterPasswordEntry").exists
        or d(resourceId="ChooseAccountCreationButton").exists,
        timeout=15,
    )


def _logout_via_overflow(d) -> bool:
    more_button = d(description="More")
    if not more_button.exists:
        return False

    if not click_then_expect(d, more_button, d(text="Log out"), timeout=SHORT_WAIT):
        return False

    logout_option = d(text="Log out")
    logout_option.click()
    time.sleep(1)

    yes_button = d(text="Yes")
    if yes_button.exists:
        return click_then_expect(
            d,
            yes_button,
            lambda: d(resourceId="EmailAddressEntry").exists
            or d(resourceId="MasterPasswordEntry").exists,
            timeout=15,
        )

    return False


def _navigate_to_start_registration(d) -> None:
    for _ in range(4):
        _dismiss_common_popups(d)

        if _is_start_registration_screen(d) or _is_create_account_screen(d):
            return

        if d(resourceId="ChooseLoginButton").exists or _is_login_screen(d):
            _navigate_to_auth_entry(d)
            continue

        if d(resourceId="CreateAccountLabel").exists:
            if not click_then_expect(
                d,
                d(resourceId="CreateAccountLabel"),
                lambda: _is_start_registration_screen(d)
                or _is_create_account_screen(d)
                or d(resourceId="ServerUrlEntry").exists
                or d(resourceId="AlertPopup").exists,
                timeout=SHORT_WAIT,
            ):
                raise RuntimeError(
                    "Failed to advance from LandingScreen to StartRegistrationScreen."
                )
            wait_for_ui_stable(d, timeout=SHORT_WAIT)
            continue

        if d(resourceId="ServerUrlEntry").exists:
            return

        wait_for_ui_stable(d, timeout=SHORT_WAIT)

    raise RuntimeError("Could not find a supported path to StartRegistrationScreen.")


def _navigate_to_auth_entry(d) -> None:
    for _ in range(6):  # Increased attempts
        _dismiss_common_popups(d)

        if (
            _is_landing_screen(d)
            or _is_login_screen(d)
            or _is_start_registration_screen(d)
            or _is_create_account_screen(d)
            or d(resourceId="ServerUrlEntry").exists
            or d(resourceId="RegionSelectorDropdown").exists
        ):
            return

        if d(resourceId="ChooseLoginButton").exists:
            if not click_then_expect(
                d,
                d(resourceId="ChooseLoginButton"),
                lambda: _is_landing_screen(d)
                or _is_login_screen(d)
                or _is_start_registration_screen(d)
                or _is_create_account_screen(d)
                or d(resourceId="ServerUrlEntry").exists
                or d(resourceId="AlertPopup").exists,
                timeout=SHORT_WAIT,
            ):
                logger.warning("Attempt to click ChooseLoginButton failed, retrying...")
            wait_for_ui_stable(d, timeout=SHORT_WAIT)
            continue

        # If we see the create account button on the welcome screen, maybe we can click it to get to the landing screen too
        if d(resourceId="ChooseAccountCreationButton").exists:
            d(resourceId="ChooseAccountCreationButton").click()
            wait_for_ui_stable(d, timeout=SHORT_WAIT)
            continue

        wait_for_ui_stable(d, timeout=SHORT_WAIT)

    raise RuntimeError("Could not reach a supported authentication entry screen.")


def _configure_self_hosted_environment(d) -> None:
    region_selector = d(resourceId="RegionSelectorDropdown")
    server_url_entry = d(resourceId="ServerUrlEntry")

    if _is_login_screen(d):
        if not click_then_expect(
            d,
            d(resourceId="NotYouLabel"),
            _is_landing_screen,
            timeout=SHORT_WAIT,
        ):
            raise RuntimeError(
                "LoginScreen did not return to LandingScreen via NotYouLabel."
            )
        wait_for_ui_stable(d, timeout=SHORT_WAIT)

    # If the URL entry is already visible, we are already in self-hosted mode or similar.
    if server_url_entry.exists:
        logger.info("ServerUrlEntry already visible, skipping environment selection.")
        wait_and_set_text(d, server_url_entry, SERVER_URL)
        if not click_then_expect(
            d,
            d(resourceId="SaveButton"),
            lambda: _is_landing_screen(d)
            or _is_start_registration_screen(d)
            or _is_create_account_screen(d),
            timeout=NETWORK_WAIT,
        ):
            raise RuntimeError("Failed to save the self-hosted environment.")
        return

    # Check if the region selector is already set to Self-hosted
    if region_selector.exists and "Self-hosted" in (region_selector.get_text() or ""):
        logger.info(
            "Region selector already shows 'Self-hosted'. Clicking to enter URL."
        )
        region_selector.click()
        time.sleep(1)
        if not server_url_entry.exists(timeout=SHORT_WAIT):
            # Fallback: if it didn't open the URL entry, maybe it needs a re-selection
            logger.info(
                "ServerUrlEntry not visible after click, re-selecting from list."
            )
            if not click_then_expect(
                d, d(text="Self-hosted"), server_url_entry, timeout=SHORT_WAIT
            ):
                raise RuntimeError("Failed to select 'Self-hosted' from the list.")
    else:
        if not click_then_expect(
            d, region_selector, d(text="Self-hosted"), timeout=SHORT_WAIT
        ):
            raise RuntimeError("Failed to open the environment selector.")

        if not click_then_expect(
            d,
            d(text="Self-hosted"),
            server_url_entry,
            timeout=SHORT_WAIT,
        ):
            raise RuntimeError(
                "Failed to navigate to the self-hosted environment screen."
            )

    wait_and_set_text(d, server_url_entry, SERVER_URL)
    if not click_then_expect(
        d,
        d(resourceId="SaveButton"),
        lambda: _is_landing_screen(d)
        or _is_start_registration_screen(d)
        or _is_create_account_screen(d),
        timeout=NETWORK_WAIT,
    ):
        raise RuntimeError("Failed to save the self-hosted environment.")


def _complete_post_registration_setup(d) -> None:
    if d(resourceId="SetUpLaterButton").exists:
        if click_then_expect(
            d,
            d(resourceId="SetUpLaterButton"),
            d(text="Confirm"),
            timeout=SHORT_WAIT,
        ):
            click_then_expect(
                d,
                d(text="Confirm"),
                lambda: d(text="Turn on later").exists
                or d(text="Continue").exists
                or d(resourceId="AddItemButton").exists,
                timeout=SHORT_WAIT,
            )

    if d(text="Turn on later").exists:
        if click_then_expect(
            d,
            d(text="Turn on later"),
            d(text="Confirm"),
            timeout=SHORT_WAIT,
        ):
            click_then_expect(
                d,
                d(text="Confirm"),
                lambda: d(text="Continue").exists
                or d(resourceId="AddItemButton").exists,
                timeout=SHORT_WAIT,
            )

    if d(text="Continue").exists and not d(resourceId="AddItemButton").exists:
        click_then_expect(
            d,
            d(text="Continue"),
            d(resourceId="AddItemButton"),
            timeout=15,
        )

    _dismiss_common_popups(d)


def _wait_for_unlocked_vault(d, timeout: float = 25.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        _dismiss_common_popups(d)
        if d(resourceId="AddItemButton").exists:
            return True
        # VaultTab present without AddItemButton means vault is unlocked but on wrong tab
        if d(resourceId="VaultTab").exists:
            d(resourceId="VaultTab").click()
            time.sleep(0.5)
            continue
        time.sleep(0.5)
    return d(resourceId="AddItemButton").exists


def _normalize_to_unlocked_vault(d, email: str, master_password: str) -> None:
    _complete_post_registration_setup(d)

    if _wait_for_unlocked_vault(d, timeout=25.0):
        return

    logger.info(
        "Unlocked vault was not reached during onboarding; relaunching and logging in to normalize state."
    )
    if not bw_attempt_login(d, email, master_password):
        raise RuntimeError(
            "Account was created, but the app could not be normalized to an unlocked vault."
        )


def _fetch_verification_token_for_email(email: str) -> str | None:
    try:
        from utils.db_container_utils import query_container
    except Exception as exc:
        logger.warning("Could not import DB helper for token lookup: %s", exc)
        return None

    db_config = {
        "container_name": os.getenv("DB_CONTAINER", "vaultwarden-db"),
        "db_type": "postgres",
        "database": os.getenv("DB_NAME", "vaultwarden"),
        "user": os.getenv("DB_USER", "bitwarden"),
        "password": os.getenv("DB_PASSWORD", "super_strong_password"),
    }

    candidate_queries = [
        (
            "SELECT email_verification_token FROM public.users "
            "WHERE email = %s AND email_verification_token IS NOT NULL",
            "email_verification_token",
        ),
        (
            "SELECT verification_token FROM public.users "
            "WHERE email = %s AND verification_token IS NOT NULL",
            "verification_token",
        ),
        (
            "SELECT token FROM public.email_verification "
            "WHERE email = %s AND token IS NOT NULL ORDER BY created_at DESC LIMIT 1",
            "token",
        ),
    ]

    for query, column in candidate_queries:
        try:
            rows = query_container(
                db_config["container_name"],
                query,
                (email,),
                db_type=db_config["db_type"],
                user=db_config["user"],
                password=db_config["password"],
                database=db_config["database"],
            )
        except Exception:
            continue

        if rows and rows[0].get(column):
            logger.info("Recovered verification token for %s from the database.", email)
            return rows[0][column]

    return None


def _ensure_app_in_foreground(
    device, package_name: str, wait_timeout: float = 30.0
) -> None:
    """
    Start the given package and ensure it reaches the foreground.

    Tries a few strategies to reduce flakiness:
    - Go HOME first to ensure a stable launcher state
    - Cold start with stop=True and wait=True
    - Fallback to a monkey-based start if needed
    """
    logger.info("Ensuring %s is in the foreground...", package_name)

    # Ensure launcher is in a stable state
    device.press("home")

    # First attempt: hard restart and wait for foreground
    device.app_start(package_name, wait=True, stop=True)
    if device.app_wait(package_name, front=True, timeout=wait_timeout):
        return

    # Second attempt: try monkey-based start
    logger.warning(
        "%s not in foreground after first start. Retrying with monkey...", package_name
    )
    device.app_start(package_name, wait=True, stop=True, use_monkey=True)
    if device.app_wait(package_name, front=True, timeout=wait_timeout):
        return

    logger.error("Failed to start %s in foreground", package_name)
    current = device.app_current()
    raise RuntimeError(f"Expected {package_name} in foreground, got: {current}")


def bw_initialize_local_host(d):
    """
    Initializes the device connection and launches the Bitwarden app
    """
    # --- Step 1: App Initialization and Server Configuration ---
    # The following steps launch the application and point it to the
    # self-hosted Vaultwarden server instance.

    # --- 1.1: App Launch ---
    logger.info("Step 1.1.1: Stopping any existing instances of %s...", BITWARDEN_PKG)
    d.app_stop(BITWARDEN_PKG)

    logger.info("Step 1.1.2: Launching %s...", BITWARDEN_PKG)
    _ensure_app_in_foreground(d, BITWARDEN_PKG, wait_timeout=30.0)

    logger.info("Waiting for the initial UI to stabilize after launch...")
    wait_for_ui_stable(d, timeout=15)
    _dismiss_common_popups(d)

    logger.info("Step 1.2.1: Navigating to the authentication entry flow...")
    _navigate_to_auth_entry(d)

    logger.info("Step 1.2.2: Configuring the self-hosted environment...")
    _configure_self_hosted_environment(d)


def bw_make_account(d, email, name, master_password):
    """
    Creates a Bitwarden account with the specified credentials
    """
    # --- Step 2: User Account Creation ---
    # The following steps walk through the UI to register a new user
    # with the provided credentials.
    logger.info("Creating account for %s", email)

    _dismiss_common_popups(d)
    if _is_landing_screen(d):
        if not click_then_expect(
            d,
            d(resourceId="CreateAccountLabel"),
            lambda: _is_start_registration_screen(d)
            or _is_create_account_screen(d)
            or d(resourceId="AlertPopup").exists,
            timeout=SHORT_WAIT,
        ):
            raise RuntimeError("Landing screen did not advance into account creation.")
        wait_for_ui_stable(d, timeout=SHORT_WAIT)
        _dismiss_common_popups(d)

    _navigate_to_start_registration(d)

    if _is_create_account_screen(d):
        logger.info("Detected CreateAccountScreen flow for %s", email)
        wait_and_set_text(d, d(resourceId="EmailAddressEntry"), email)
        wait_and_set_text(d, d(resourceId="MasterPasswordEntry"), master_password)
        wait_and_set_text(
            d, d(resourceId="ConfirmMasterPasswordEntry"), master_password
        )

        accept_policies = d(description="AcceptPoliciesToggle")
        if accept_policies.exists:
            try:
                info = accept_policies.info
                if not info.get("checked", False):
                    wait_and_click(d, accept_policies)
                    wait_for_ui_stable(d, timeout=SHORT_WAIT)
            except Exception:
                wait_and_click(d, accept_policies)
                wait_for_ui_stable(d, timeout=SHORT_WAIT)

        if not click_then_expect(
            d,
            d(resourceId="SubmitButton"),
            lambda: d(resourceId="EmailAddressEntry").exists
            or d(resourceId="MasterPasswordEntry").exists
            or d(resourceId="AlertPopup").exists
            or d(resourceId="AddItemButton").exists,
            timeout=20,
        ):
            raise RuntimeError("CreateAccountScreen did not submit successfully.")

        _dismiss_common_popups(d)
        _normalize_to_unlocked_vault(d, email, master_password)
        return

    # Step 2.1: Enter the email address
    logger.info("Step 2.1: Entering email address: %s...", email)
    wait_and_set_text(d, d(resourceId="EmailAddressEntry"), email)

    # Step 2.2: Enter the user's name
    logger.info("Step 2.2: Entering name: %s...", name)
    wait_and_set_text(d, d(resourceId="NameEntry"), name)

    # Step 2.3: Click the Continue button to proceed with account creation
    logger.info("Step 2.3: Clicking Continue button...")
    if not click_then_expect(
        d,
        d(resourceId="ContinueButton"),
        lambda: d(resourceId="MasterPasswordEntry").exists
        or d(resourceId="OpenEmailApp").exists
        or d(resourceId="AlertPopup").exists,
        timeout=20,
    ):
        raise RuntimeError(
            "Start Registration did not advance to the expected next screen."
        )

    if d(resourceId="OpenEmailApp").exists:
        verification_token = _fetch_verification_token_for_email(email)
        if not verification_token:
            raise RuntimeError(
                "Registration reached CheckEmailScreen and no verification token could be recovered."
            )
        deep_link = (
            "bitwarden://complete-registration/finish-signup"
            f"?email={quote(email)}&token={quote(verification_token)}&fromEmail=true"
        )
        d.shell(f'am start -a android.intent.action.VIEW -d "{deep_link}"')
        if not d(resourceId="MasterPasswordEntry").wait(timeout=20):
            raise RuntimeError(
                "Recovered verification token but deep link did not open Complete Registration."
            )

    _dismiss_common_popups(d)

    # Step 2.4: Enter the master password
    logger.info("Step 2.4: Entering master password: %s...", master_password)
    wait_and_set_text(d, d(resourceId="MasterPasswordEntry"), master_password)

    # Step 2.5: Enter the master password confirmation
    logger.info(
        "Step 2.5: Entering master password confirmation: %s...", master_password
    )
    wait_and_set_text(d, d(resourceId="ConfirmMasterPasswordEntry"), master_password)

    # Step 2.6: Click the Next button to proceed with account creation
    logger.info("Step 2.6: Clicking Next button...")
    next_button = d(text="Next")
    if not _scroll_until_visible(d, next_button):
        raise RuntimeError(
            "Complete Registration CTA was not visible after scrolling the form."
        )
    if not click_then_expect(
        d,
        next_button,
        lambda: d(resourceId="SetUpLaterButton").exists
        or d(text="Turn on later").exists
        or d(text="Continue").exists
        or d(resourceId="AddItemButton").exists
        or d(resourceId="AlertPopup").exists,
        timeout=20,
    ):
        raise RuntimeError("Complete Registration did not advance after submitting.")

    _normalize_to_unlocked_vault(d, email, master_password)

    logger.info("Account for %s created successfully", email)


def bw_create_new_cipher(d, cipher):
    """
    Creates a new cipher entry in the vault
    """
    # --- Step 3: Cipher Creation ---
    # The following steps create a new login cipher in the user's vault.
    logger.info("Creating cipher: %s", cipher["name"])

    # Step 3.1: Click the main '+' button to add a new item.
    logger.info("Step 3.1: Clicking the 'Add Item' button...")
    if not click_then_expect(
        d,
        d(resourceId="AddItemButton"),
        lambda: d(resourceId="AlertSelectionOption", text="Login").exists
        or d(resourceId="AlertPopup").exists,
        timeout=SHORT_WAIT,
    ):
        raise RuntimeError("Add Item did not open the item type selector.")

    # Step 3.2: Select "Login" from the item type dialog.
    logger.info("Step 3.2: Selecting 'Login' as the item type...")
    if not click_then_expect(
        d,
        d(resourceId="AlertSelectionOption", text="Login"),
        lambda: d(resourceId="ItemNameEntry").exists
        or d(resourceId="AcceptAlertButton").exists
        or d(resourceId="AlertPopup").exists,
        timeout=SHORT_WAIT,
    ):
        raise RuntimeError("Login item type did not open the cipher form.")

    # Handle the optional "Bitwarden Autofill Service" dialog that may appear.
    logger.info("Step 3.2: Checking for Autofill Service dialog...")
    if (
        d(resourceId="AcceptAlertButton").exists(timeout=1)
        and not d(resourceId="ItemNameEntry").exists
    ):
        logger.info("Step 3.2: Autofill dialog found. Clicking 'Okay'...")
        if not click_then_expect(
            d,
            d(resourceId="AcceptAlertButton"),
            d(resourceId="ItemNameEntry"),
            timeout=SHORT_WAIT,
        ):
            raise RuntimeError("Autofill dialog did not dismiss to the cipher form.")

    _dismiss_common_popups(d)

    # Step 3.3: Enter the item name from the cipher data.
    logger.info("Step 3.3: Entering item name '%s'...", cipher["name"])
    wait_and_set_text(d, d(resourceId="ItemNameEntry"), cipher["name"])

    # Step 3.4: Enter the username from the cipher data.
    logger.info("Step 3.4: Entering username '%s'...", cipher["username"])
    wait_and_set_text(d, d(resourceId="LoginUsernameEntry"), cipher["username"])

    # Step 3.5: Enter the password from the cipher data.
    logger.info("Step 3.5: Entering password '%s'...", cipher["password"])
    wait_and_set_text(d, d(resourceId="LoginPasswordEntry"), cipher["password"])

    # Step 3.6: Enter the website URI from the cipher data.
    logger.info("Step 3.6: Entering website URI '%s'...", cipher["website"])
    wait_and_set_text(d, d(resourceId="LoginUriEntry"), cipher["website"])

    # Step 3.7: Click the Save button to save the cipher.
    logger.info("Step 3.7: Clicking the Save button...")
    if not click_then_expect(
        d,
        d(resourceId="SaveButton"),
        lambda: d(resourceId="AddItemButton").exists
        or d(resourceId="AlertPopup").exists,
        timeout=15,
    ):
        raise RuntimeError("Saving the cipher did not return to the vault screen.")

    _dismiss_common_popups(d)

    logger.info("Finished creating cipher: %s", cipher["name"])


def bw_lock_and_logout(d, email: str | None = None):
    """
    Locks the vault and logs out
    """
    logger.info("Logging out of the current account")
    _dismiss_common_popups(d)

    if email and d(resourceId="AddItemButton").exists:
        if _logout_via_account_actions(d, email):
            logger.info("Logout complete.")
            return

    if _logout_via_overflow(d):
        logger.info("Logout complete.")
        return

    raise RuntimeError("Failed to log out from the unlocked vault.")


def bw_attempt_login(d, email, password):
    """
    Attempts to login to the Bitwarden app
    """
    try:
        # --- Stop any previous instances and start fresh ---
        logger.info("Stopping any existing instances of %s...", BITWARDEN_PKG)
        d.app_stop(BITWARDEN_PKG)

        logger.info("Launching %s...", BITWARDEN_PKG)
        _ensure_app_in_foreground(d, BITWARDEN_PKG, wait_timeout=30.0)

        logger.info("Waiting for the initial UI to stabilize after launch...")
        wait_for_ui_stable(d, timeout=15)
        _dismiss_common_popups(d)

        if d(resourceId="AddItemButton").exists:
            logger.info("Unlocked vault detected. Logging out before login attempt.")
            try:
                active_email = None
                if _open_account_switcher(d):
                    active_email = _find_active_account_email(d)
                    d.press("back")
                    wait_for_ui_stable(d, timeout=SHORT_WAIT)
                bw_lock_and_logout(d, active_email)
            except Exception as exc:
                logger.warning("Could not pre-logout from unlocked state: %s", exc)

        if _is_login_screen(d):
            label_text = ""
            if d(resourceId="LoggingInAsLabel").exists:
                try:
                    label_text = d(resourceId="LoggingInAsLabel").get_text()
                except Exception:
                    label_text = ""
            if email not in label_text:
                logger.info(
                    "Login screen is prefilled for a different account. Choosing 'Not you?'."
                )
                if click_then_expect(
                    d,
                    d(resourceId="NotYouLabel"),
                    d(resourceId="EmailAddressEntry"),
                    timeout=SHORT_WAIT,
                ):
                    wait_for_ui_stable(d, timeout=SHORT_WAIT)

        if (
            d(resourceId="EmailAddressEntry").exists
            and not d(resourceId="NameEntry").exists
        ):
            logger.info("Entering email: %s...", email)
            wait_and_set_text(d, d(resourceId="EmailAddressEntry"), email)

            logger.info("Clicking 'Continue'...")
            if not click_then_expect(
                d,
                d(resourceId="ContinueButton"),
                lambda: d(resourceId="MasterPasswordEntry").exists
                or d(resourceId="AlertPopup").exists,
                timeout=15,
            ):
                logger.error("Landing screen did not advance to the Login screen.")
                return False

        if not d(resourceId="MasterPasswordEntry").exists:
            logger.error("Master password field is not visible for %s.", email)
            return False

        _dismiss_common_popups(d)

        logger.info("Entering master password...")
        wait_and_set_text(d, d(resourceId="MasterPasswordEntry"), password)

        # --- Submitting and Verifying Outcome ---
        submit_button = None
        if _is_login_screen(d):
            submit_button = d(resourceId="LogInWithMasterPasswordButton")
        elif _is_vault_unlock_screen(d):
            submit_button = d(resourceId="UnlockVaultButton")

        if submit_button is None:
            logger.error(
                "Master password is visible, but neither LoginScreen nor VaultUnlockScreen submit controls were detected."
            )
            return False

        logger.info("Submitting authentication on the current Bitwarden screen...")
        if not click_then_expect(
            d,
            submit_button,
            lambda: d(resourceId="VaultTab").exists
            or d(resourceId="AddItemButton").exists
            or d(resourceId="MasterPasswordEntry").exists
            or (
                d(resourceId="AlertPopup").exists
                and not d(resourceId="AlertProgressIndicator").exists
            ),
            timeout=30,
        ):
            logger.error(
                "Login submission did not produce an expected post-submit state."
            )
            return False

        # Check success first — if vault is visible, we're done regardless of overlay state
        if d(resourceId="VaultTab").exists or d(resourceId="AddItemButton").exists:
            logger.info("Login successful. Main vault is visible.")
            return True

        # Check for real error dialogs (loading overlay has AlertProgressIndicator; skip it)
        if (
            d(resourceId="AlertPopup").exists
            and not d(resourceId="AlertProgressIndicator").exists
        ):
            logger.warning("Error dialog detected. Dismissing...")
            _dismiss_common_popups(d)
            logger.error("Login failed due to error dialog.")
            return False

        # Success is defined by the appearance of the main vault screen's header.
        # A failed login will not proceed to this screen.
        logger.info("Verifying login outcome...")
        if (
            d(resourceId="VaultTab").wait(timeout=5.0)
            or d(resourceId="AddItemButton").exists
        ):
            logger.info("Login successful. Main vault is visible.")
            return True
        else:
            # Log a quick diagnostic snapshot to aid debugging
            missing = []
            if not d(resourceId="VaultTab").exists:
                missing.append("VaultTab")
            if not d(resourceId="AddItemButton").exists:
                missing.append("AddItemButton")
            logger.error(
                "Main vault not visible after timeout. Missing: %s", ", ".join(missing)
            )
            return False

    except Exception as e:
        logger.error("An unexpected error occurred during UI automation: %s", e)
        # Dump the UI hierarchy to the console for debugging (guarded)
        try:
            logger.error("%s", d.dump_hierarchy())
        except Exception:
            pass
        return False
