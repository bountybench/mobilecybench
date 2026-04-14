"""
Bitwarden-specific UI workflows built on top of generic ui_utils primitives.

These functions orchestrate common Bitwarden flows such as initial setup,
account creation, cipher creation, logging out, and attempting login.

UI selectors are documented in ``bw_ui_source`` (aligned with ``apps/bitwarden/codebase``).
"""

# ruff: noqa: I001
# Imports: keep ``utils`` before package-relative imports (E402 for script entrypoints).

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

from .bw_ui_source import (  # noqa: E402
    ComposeTags as CT,
    LOG_IN_WITH_MASTER_PASSWORD_TEXT_PREFIX,
    StringsEn as SE,
)
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


def _set_bitwarden_password_field(d, field, password: str) -> None:
    """
    Fill a Bitwarden Compose password field so ViewModel state updates.

    UiAutomator ``set_text`` often updates the visible field without firing
    ``onValueChange``, leaving CTAs disabled (e.g. CompleteRegistration ``Next``).
    IME input matches real typing and enables ``validSubmissionReady``.
    """

    def _field_reports_focus() -> bool:
        try:
            return bool((field.info or {}).get("focused"))
        except Exception:
            return False

    wait_and_click(d, field)
    time.sleep(0.2)
    if not _field_reports_focus():
        time.sleep(0.35)
        try:
            wait_and_click(d, field)
        except Exception as exc:
            logger.debug("Second focus click on password field: %s", exc)
        time.sleep(0.15)

    try:
        field.clear_text()
    except Exception:
        pass
    try:
        d.send_keys(password, clear=True)
    except Exception as exc:
        logger.warning("IME password entry failed (%s); using set_text fallback.", exc)
        wait_and_set_text(d, field, password)
        return
    wait_for_ui_stable(d, min_consecutive=2, timeout=10)


def _fill_bitwarden_master_password_fields(d, password: str) -> None:
    """Set master password and confirmation when the confirm field exists."""
    master = d(resourceId=CT.MASTER_PASSWORD_ENTRY)
    _set_bitwarden_password_field(d, master, password)
    confirm = d(resourceId=CT.CONFIRM_MASTER_PASSWORD_ENTRY)
    if not confirm.exists:
        return
    _set_bitwarden_password_field(d, confirm, password)


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
        if _resource_matches(node.attrib.get("resource-id"), CT.ACCOUNT_CELL):
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
        if _descendant_text(cell, CT.ACCOUNT_EMAIL_LABEL) == email:
            return _parse_bounds_center(cell.attrib.get("bounds"))
    return None


def _find_active_account_email(d) -> str | None:
    root = _dump_ui_root(d)
    if root is None:
        return None

    for cell in _iter_account_cells(root):
        if _has_descendant_resource(cell, CT.ACTIVE_VAULT_ICON):
            return _descendant_text(cell, CT.ACCOUNT_EMAIL_LABEL)
    return None


def _dismiss_alert_popup(d, timeout: float = 1.0) -> bool:
    alert = d(resourceId=CT.ALERT_POPUP)
    accept = d(resourceId=CT.ACCEPT_ALERT_BUTTON)
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

        # Handle generic continue/next/yes buttons that might appear in modals
        # without the specific AcceptAlertButton tag.
        dismissed = False
        if d(resourceId=CT.ALERT_POPUP).exists:
            for label in (SE.CONTINUE, SE.NEXT, SE.YES, SE.CONFIRM):
                btn = d(resourceId=CT.ALERT_POPUP).child(text=label)
                if not btn.exists:
                    btn = d(resourceId=CT.ALERT_POPUP).child(description=label)
                if btn.exists:
                    logger.info(
                        "Dismissing Bitwarden alert popup via generic button: %s", label
                    )
                    wait_and_click(d, btn)
                    dismissed = True
                    break

        if dismissed:
            wait_for_ui_stable(d, timeout=SHORT_WAIT)
            continue
        break


def _vault_unlocked_visible(d) -> bool:
    """True when the vault item-listing screen is actually ready for item creation."""
    return bool(d(resourceId=CT.ADD_ITEM_BUTTON).exists)


def _auth_submit_terminal_state(d) -> bool:
    """
    True once login/unlock either opened the vault or surfaced a stable (non-spinner) modal.

    Must not use MasterPasswordEntry: it often stays in the hierarchy while the server
    round-trip is in flight, which caused click_then_expect to succeed before navigation.
    """
    if _vault_unlocked_visible(d):
        return True
    if (
        d(resourceId=CT.ALERT_POPUP).exists
        and not d(resourceId=CT.ALERT_PROGRESS_INDICATOR).exists
    ):
        return True
    return False


def _select_auth_submit_control(d):
    """Return the primary submit control for the current auth or registration password step."""
    max_sw = 10

    # Create-account / complete-registration screens expose ConfirmMasterPasswordEntry.
    # CTA is often untagged "Next" or toolbar SubmitButton. When this branch runs from
    # ``bw_attempt_login`` (e.g. after relaunch), we must finish that step — do not fall
    # through to Log in / Unlock, which would scroll pointlessly or match the wrong control.
    if d(resourceId=CT.CONFIRM_MASTER_PASSWORD_ENTRY).exists:
        _scroll_to(d, text=SE.NEXT)
        _scroll_to(d, resource_id=CT.SUBMIT_BUTTON)
        for candidate in (
            d(text=SE.NEXT),
            d(description=SE.NEXT),
            d(textContains=SE.NEXT),
            d(resourceId=CT.SUBMIT_BUTTON),
            d(text=SE.CONTINUE),
            d(resourceId=CT.CONTINUE_BUTTON),
        ):
            if _scroll_until_visible(d, candidate, max_swipes=max_sw):
                return candidate
        return None

    # Normal Login/Unlock buttons
    login_button = d(resourceId=CT.LOG_IN_WITH_MASTER_PASSWORD_BUTTON)
    if _scroll_until_visible(d, login_button, max_swipes=max_sw):
        return login_button

    unlock_button = d(resourceId=CT.UNLOCK_VAULT_BUTTON)
    if _scroll_until_visible(d, unlock_button, max_swipes=max_sw):
        return unlock_button

    # Fallback to "Set up later" or "Turn on later" if an onboarding screen is blocking
    # but a master password field was detected.
    for candidate in (
        d(resourceId=CT.SET_UP_LATER_BUTTON),
        d(text=SE.TURN_ON_LATER),
    ):
        if candidate.exists:
            return candidate

    login_label = d(text=SE.LOG_IN_WITH_MASTER_PASSWORD)
    if _scroll_until_visible(d, login_label, max_swipes=max_sw):
        return login_label

    login_partial = d(textContains=LOG_IN_WITH_MASTER_PASSWORD_TEXT_PREFIX)
    if _scroll_until_visible(d, login_partial, max_swipes=max_sw):
        return login_partial

    unlock_label = d(text=SE.UNLOCK)
    if _scroll_until_visible(d, unlock_label, max_swipes=max_sw):
        return unlock_label

    unlock_desc = d(description=SE.UNLOCK)
    if _scroll_until_visible(d, unlock_desc, max_swipes=max_sw):
        return unlock_desc

    return None


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
        d(resourceId=CT.EMAIL_ADDRESS_ENTRY).exists
        and d(resourceId=CT.NAME_ENTRY).exists
        and d(resourceId=CT.CONTINUE_BUTTON).exists
    )


def _scroll_to(d, resource_id: str = None, text: str = None) -> bool:
    """
    Attempts to scroll to an element within a scrollable container.
    """
    if resource_id and d(resourceId=resource_id).exists:
        return True
    if text and d(text=text).exists:
        return True

    try:
        scrollable = d(scrollable=True)
        if scrollable.exists:
            if resource_id:
                if scrollable.scroll.to(resourceId=resource_id):
                    return True
            if text:
                if scrollable.scroll.to(text=text):
                    return True
    except Exception as exc:
        logger.debug("Standard scroll attempt failed: %s", exc)

    # Fallback to manual swipes if standard scrolling fails or container isn't 'scrollable'
    for _ in range(3):
        d.swipe_ext("up", scale=0.7)
        time.sleep(1)
        if resource_id and d(resourceId=resource_id).exists:
            return True
        if text and d(text=text).exists:
            return True
    return False


def _is_landing_screen(d) -> bool:
    # A LandingScreen should have an email field and either a Create Account label or the Region/Environment selector.
    if not d(resourceId=CT.EMAIL_ADDRESS_ENTRY).exists:
        return False

    # Stricter check: if NameEntry exists, we are on the StartRegistrationScreen
    if d(resourceId=CT.NAME_ENTRY).exists:
        return False

    if (
        d(resourceId=CT.CREATE_ACCOUNT_LABEL).exists
        or d(resourceId=CT.REGION_SELECTOR_DROPDOWN).exists
        or d(resourceId=CT.CONTINUE_BUTTON).exists
    ):
        return True

    # Try scrolling to find the CreateAccountLabel if it's off-screen
    return _scroll_to(d, resource_id=CT.CREATE_ACCOUNT_LABEL)


def _is_create_account_screen(d) -> bool:
    # CreateAccountScreen.kt — full registration form + toolbar SubmitButton (not Next).
    return (
        d(resourceId=CT.EMAIL_ADDRESS_ENTRY).exists
        and d(resourceId=CT.MASTER_PASSWORD_ENTRY).exists
        and d(resourceId=CT.CONFIRM_MASTER_PASSWORD_ENTRY).exists
        and d(resourceId=CT.SUBMIT_BUTTON).exists
    )


def _is_login_screen(d) -> bool:
    if not d(resourceId=CT.MASTER_PASSWORD_ENTRY).exists:
        return False
    if d(resourceId=CT.CONFIRM_MASTER_PASSWORD_ENTRY).exists:
        return False
    return bool(
        d(resourceId=CT.LOG_IN_WITH_MASTER_PASSWORD_BUTTON).exists
        or d(resourceId=CT.LOGGING_IN_AS_LABEL).exists
        or d(text=SE.LOG_IN_WITH_MASTER_PASSWORD).exists
    )


def _is_vault_unlock_screen(d) -> bool:
    if not d(resourceId=CT.MASTER_PASSWORD_ENTRY).exists:
        return False
    if d(resourceId=CT.CONFIRM_MASTER_PASSWORD_ENTRY).exists:
        return False
    return bool(d(resourceId=CT.UNLOCK_VAULT_BUTTON).exists or d(text=SE.UNLOCK).exists)


def _open_account_switcher(d, expected_account_email: str | None = None) -> bool:
    account_button = d(resourceId=CT.CURRENT_ACTIVE_ACCOUNT)
    if not account_button.exists:
        account_button = d(description=SE.ACCOUNT)
    if not account_button.exists:
        return False

    def switcher_visible() -> bool:
        if expected_account_email:
            return d(text=expected_account_email).exists
        return (
            d(resourceId=CT.ACCOUNT_LIST_VIEW).exists
            or d(resourceId=CT.ADD_ACCOUNT_BUTTON).exists
            or d(resourceId=CT.ACCOUNT_EMAIL_LABEL).exists
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
        d(text=SE.LOG_OUT).exists
        or d(text=SE.LOCK).exists
        or d(text=SE.REMOVE_ACCOUNT).exists
    )


def _logout_via_account_actions(d, email: str) -> bool:
    if not _show_account_actions(d, email):
        return False

    logout_option = d(text=SE.LOG_OUT)
    if not logout_option.exists:
        return False

    if not click_then_expect(d, logout_option, d(text=SE.YES), timeout=SHORT_WAIT):
        return False

    return click_then_expect(
        d,
        d(text=SE.YES),
        lambda: d(resourceId=CT.EMAIL_ADDRESS_ENTRY).exists
        or d(resourceId=CT.MASTER_PASSWORD_ENTRY).exists
        or d(resourceId=CT.CHOOSE_ACCOUNT_CREATION_BUTTON).exists,
        timeout=15,
    )


def _logout_via_overflow(d) -> bool:
    more_button = d(description=SE.MORE)
    if not more_button.exists:
        return False

    if not click_then_expect(d, more_button, d(text=SE.LOG_OUT), timeout=SHORT_WAIT):
        return False

    logout_option = d(text=SE.LOG_OUT)
    logout_option.click()
    time.sleep(1)

    yes_button = d(text=SE.YES)
    if yes_button.exists:
        return click_then_expect(
            d,
            yes_button,
            lambda: d(resourceId=CT.EMAIL_ADDRESS_ENTRY).exists
            or d(resourceId=CT.MASTER_PASSWORD_ENTRY).exists,
            timeout=15,
        )

    return False


def _navigate_to_start_registration(d) -> None:
    for _ in range(4):
        _dismiss_common_popups(d)

        if _is_start_registration_screen(d) or _is_create_account_screen(d):
            return

        if d(resourceId=CT.CHOOSE_LOGIN_BUTTON).exists or _is_login_screen(d):
            _navigate_to_auth_entry(d)
            continue

        if d(resourceId=CT.CREATE_ACCOUNT_LABEL).exists or _scroll_to(
            d, resource_id=CT.CREATE_ACCOUNT_LABEL
        ):
            if not click_then_expect(
                d,
                d(resourceId=CT.CREATE_ACCOUNT_LABEL),
                lambda: _is_start_registration_screen(d)
                or _is_create_account_screen(d)
                or d(resourceId=CT.SERVER_URL_ENTRY).exists
                or d(resourceId=CT.ALERT_POPUP).exists,
                timeout=SHORT_WAIT,
            ):
                raise RuntimeError(
                    "Failed to advance from LandingScreen to StartRegistrationScreen."
                )
            wait_for_ui_stable(d, timeout=SHORT_WAIT)
            continue

        if d(resourceId=CT.SERVER_URL_ENTRY).exists:
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
            or d(resourceId=CT.SERVER_URL_ENTRY).exists
            or d(resourceId=CT.REGION_SELECTOR_DROPDOWN).exists
        ):
            return

        if d(resourceId=CT.CHOOSE_LOGIN_BUTTON).exists:
            if not click_then_expect(
                d,
                d(resourceId=CT.CHOOSE_LOGIN_BUTTON),
                lambda: _is_landing_screen(d)
                or _is_login_screen(d)
                or _is_start_registration_screen(d)
                or _is_create_account_screen(d)
                or d(resourceId=CT.SERVER_URL_ENTRY).exists
                or d(resourceId=CT.ALERT_POPUP).exists,
                timeout=SHORT_WAIT,
            ):
                logger.warning("Attempt to click ChooseLoginButton failed, retrying...")
            wait_for_ui_stable(d, timeout=SHORT_WAIT)
            continue

        # If we see the create account button on the welcome screen, maybe we can click it to get to the landing screen too
        if d(resourceId=CT.CHOOSE_ACCOUNT_CREATION_BUTTON).exists:
            d(resourceId=CT.CHOOSE_ACCOUNT_CREATION_BUTTON).click()
            wait_for_ui_stable(d, timeout=SHORT_WAIT)
            continue

        wait_for_ui_stable(d, timeout=SHORT_WAIT)

    raise RuntimeError("Could not reach a supported authentication entry screen.")


def _configure_self_hosted_environment(d) -> None:
    region_selector = d(resourceId=CT.REGION_SELECTOR_DROPDOWN)
    server_url_entry = d(resourceId=CT.SERVER_URL_ENTRY)

    if _is_login_screen(d):
        if not click_then_expect(
            d,
            d(resourceId=CT.NOT_YOU_LABEL),
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
            d(resourceId=CT.SAVE_BUTTON),
            lambda: _is_landing_screen(d)
            or _is_start_registration_screen(d)
            or _is_create_account_screen(d),
            timeout=NETWORK_WAIT,
        ):
            raise RuntimeError("Failed to save the self-hosted environment.")
        return

    # Check if the region selector is already set to Self-hosted
    if (
        region_selector.exists or _scroll_to(d, resource_id=CT.REGION_SELECTOR_DROPDOWN)
    ) and "Self-hosted" in (region_selector.get_text() or ""):
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
                d, d(text=SE.SELF_HOSTED), server_url_entry, timeout=SHORT_WAIT
            ):
                raise RuntimeError("Failed to select 'Self-hosted' from the list.")
    else:
        if not (
            region_selector.exists
            or _scroll_to(d, resource_id=CT.REGION_SELECTOR_DROPDOWN)
        ):
            raise RuntimeError("RegionSelectorDropdown not found.")

        if not click_then_expect(
            d, region_selector, d(text=SE.SELF_HOSTED), timeout=SHORT_WAIT
        ):
            raise RuntimeError("Failed to open the environment selector.")

        if not click_then_expect(
            d,
            d(text=SE.SELF_HOSTED),
            server_url_entry,
            timeout=SHORT_WAIT,
        ):
            raise RuntimeError(
                "Failed to navigate to the self-hosted environment screen."
            )

    wait_and_set_text(d, server_url_entry, SERVER_URL)
    if not click_then_expect(
        d,
        d(resourceId=CT.SAVE_BUTTON),
        lambda: _is_landing_screen(d)
        or _is_start_registration_screen(d)
        or _is_create_account_screen(d),
        timeout=NETWORK_WAIT,
    ):
        raise RuntimeError("Failed to save the self-hosted environment.")


def _complete_post_registration_setup(d) -> None:
    """
    Dismiss onboarding/setup screens after registration (biometrics, keep-safe, etc).

    Bitwarden versions vary in which screens they show and in what order. This loop
    aggressively dismisses everything until the vault (AddItemButton) is visible.
    """
    max_rounds = 10
    for round_idx in range(max_rounds):
        _dismiss_common_popups(d)

        if _vault_unlocked_visible(d):
            logger.info("Reached unlocked vault after %d dismissal rounds.", round_idx)
            return

        # Check for various 'Skip' or 'Later' buttons
        setup_later = d(resourceId=CT.SET_UP_LATER_BUTTON)
        if setup_later.exists:
            logger.info("Dismissing 'Set up later' onboarding screen.")
            setup_later.click()
            wait_for_ui_stable(d, timeout=SHORT_WAIT)
            continue

        turn_on_later = d(text=SE.TURN_ON_LATER)
        if turn_on_later.exists:
            logger.info("Dismissing 'Turn on later' onboarding screen.")
            turn_on_later.click()
            wait_for_ui_stable(d, timeout=SHORT_WAIT)
            continue

        # Generic Next/Continue/Confirm/Yes buttons
        for label in (SE.CONTINUE, SE.NEXT, SE.CONFIRM, SE.YES):
            btn = d(text=label)
            if not btn.exists:
                btn = d(description=label)
            if btn.exists:
                logger.info(
                    "Dismissing onboarding screen via generic button: %s", label
                )
                btn.click()
                wait_for_ui_stable(d, timeout=SHORT_WAIT)
                break
        else:
            # If no buttons matched and vault not visible, try a manual back press
            # but only if we're not on a primary screen (EmailEntry / MasterPasswordEntry).
            if (
                not d(resourceId=CT.EMAIL_ADDRESS_ENTRY).exists
                and not d(resourceId=CT.MASTER_PASSWORD_ENTRY).exists
            ):
                logger.info(
                    "No onboarding controls detected; attempting back-press to clear potential modal."
                )
                d.press("back")
                wait_for_ui_stable(d, timeout=SHORT_WAIT)
            else:
                break

    if not _vault_unlocked_visible(d):
        logger.warning(
            "Finished onboarding loop but AddItemButton is still not visible."
        )


def _wait_for_unlocked_vault(d, timeout: float = 35.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        _dismiss_common_popups(d)
        if d(resourceId=CT.ADD_ITEM_BUTTON).exists:
            return True
        if d(resourceId=CT.VAULT_TAB).exists:
            d(resourceId=CT.VAULT_TAB).click()
            time.sleep(0.5)
            continue
        time.sleep(0.5)
    return d(resourceId=CT.ADD_ITEM_BUTTON).exists


def _normalize_to_unlocked_vault(d, email: str, master_password: str) -> None:
    _complete_post_registration_setup(d)

    if _wait_for_unlocked_vault(d, timeout=45.0):
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
        # LandingScreen can match via RegionSelectorDropdown / ContinueButton while the
        # "Create an account" control (CreateAccountLabel) sits below the fold — _scroll_to
        # is weaker than _scroll_until_visible for tall Compose layouts.
        create_by_id = d(resourceId=CT.CREATE_ACCOUNT_LABEL)
        create_by_text = d(text=SE.CREATE_AN_ACCOUNT)
        if not _scroll_until_visible(d, create_by_id):
            _scroll_until_visible(d, create_by_text)
        if create_by_id.exists:
            create_entry = create_by_id
        elif create_by_text.exists:
            create_entry = create_by_text
        else:
            raise RuntimeError(
                "Could not find account creation control on LandingScreen "
                "(expected CreateAccountLabel or text 'Create an account')."
            )
        if not click_then_expect(
            d,
            create_entry,
            lambda: _is_start_registration_screen(d)
            or _is_create_account_screen(d)
            or d(resourceId=CT.ALERT_POPUP).exists,
            timeout=15,
        ):
            raise RuntimeError("Landing screen did not advance into account creation.")
        wait_for_ui_stable(d, timeout=SHORT_WAIT)
        _dismiss_common_popups(d)

    _navigate_to_start_registration(d)

    if _is_create_account_screen(d):
        logger.info("Detected CreateAccountScreen flow for %s", email)
        wait_and_set_text(d, d(resourceId=CT.EMAIL_ADDRESS_ENTRY), email)
        _fill_bitwarden_master_password_fields(d, master_password)

        accept_policies = d(description=CT.ACCEPT_POLICIES_TOGGLE)
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
            d(resourceId=CT.SUBMIT_BUTTON),
            lambda: d(resourceId=CT.EMAIL_ADDRESS_ENTRY).exists
            or d(resourceId=CT.MASTER_PASSWORD_ENTRY).exists
            or d(resourceId=CT.ALERT_POPUP).exists
            or d(resourceId=CT.ADD_ITEM_BUTTON).exists,
            timeout=20,
        ):
            raise RuntimeError("CreateAccountScreen did not submit successfully.")

        _dismiss_common_popups(d)
        _normalize_to_unlocked_vault(d, email, master_password)
        return

    # Step 2.1: Enter the email address
    logger.info("Step 2.1: Entering email address: %s...", email)
    wait_and_set_text(d, d(resourceId=CT.EMAIL_ADDRESS_ENTRY), email)

    # Step 2.2: Enter the user's name
    logger.info("Step 2.2: Entering name: %s...", name)
    wait_and_set_text(d, d(resourceId=CT.NAME_ENTRY), name)

    # Step 2.3: Click the Continue button to proceed with account creation
    logger.info("Step 2.3: Clicking Continue button...")
    if not click_then_expect(
        d,
        d(resourceId=CT.CONTINUE_BUTTON),
        lambda: d(resourceId=CT.MASTER_PASSWORD_ENTRY).exists
        or d(resourceId=CT.OPEN_EMAIL_APP).exists
        or d(resourceId=CT.ALERT_POPUP).exists,
        timeout=20,
    ):
        raise RuntimeError(
            "Start Registration did not advance to the expected next screen."
        )

    if d(resourceId=CT.OPEN_EMAIL_APP).exists:
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
        if not d(resourceId=CT.MASTER_PASSWORD_ENTRY).wait(timeout=20):
            raise RuntimeError(
                "Recovered verification token but deep link did not open Complete Registration."
            )

    _dismiss_common_popups(d)

    # Step 2.4: Enter the master password
    logger.info("Step 2.4: Entering master password: %s...", master_password)
    _fill_bitwarden_master_password_fields(d, master_password)

    # Step 2.6: Click the Next button to proceed with account creation
    logger.info("Step 2.6: Clicking Next button...")
    next_button = d(text=SE.NEXT)
    if not _scroll_until_visible(d, next_button):
        raise RuntimeError(
            "Complete Registration CTA was not visible after scrolling the form."
        )
    if not click_then_expect(
        d,
        next_button,
        lambda: d(resourceId=CT.SET_UP_LATER_BUTTON).exists
        or d(text=SE.TURN_ON_LATER).exists
        or d(text=SE.CONTINUE).exists
        or d(resourceId=CT.ADD_ITEM_BUTTON).exists
        or d(resourceId=CT.ALERT_POPUP).exists,
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
        d(resourceId=CT.ADD_ITEM_BUTTON),
        lambda: d(resourceId=CT.ALERT_SELECTION_OPTION, text=SE.TYPE_LOGIN).exists
        or d(resourceId=CT.ALERT_POPUP).exists,
        timeout=SHORT_WAIT,
    ):
        raise RuntimeError("Add Item did not open the item type selector.")

    # Step 3.2: Select "Login" from the item type dialog.
    logger.info("Step 3.2: Selecting 'Login' as the item type...")
    if not click_then_expect(
        d,
        d(resourceId=CT.ALERT_SELECTION_OPTION, text=SE.TYPE_LOGIN),
        lambda: d(resourceId=CT.ITEM_NAME_ENTRY).exists
        or d(resourceId=CT.ACCEPT_ALERT_BUTTON).exists
        or d(resourceId=CT.ALERT_POPUP).exists,
        timeout=SHORT_WAIT,
    ):
        raise RuntimeError("Login item type did not open the cipher form.")

    # Handle the optional "Bitwarden Autofill Service" dialog that may appear.
    logger.info("Step 3.2: Checking for Autofill Service dialog...")
    if (
        d(resourceId=CT.ACCEPT_ALERT_BUTTON).exists(timeout=1)
        and not d(resourceId=CT.ITEM_NAME_ENTRY).exists
    ):
        logger.info("Step 3.2: Autofill dialog found. Clicking 'Okay'...")
        if not click_then_expect(
            d,
            d(resourceId=CT.ACCEPT_ALERT_BUTTON),
            d(resourceId=CT.ITEM_NAME_ENTRY),
            timeout=SHORT_WAIT,
        ):
            raise RuntimeError("Autofill dialog did not dismiss to the cipher form.")

    _dismiss_common_popups(d)

    # Step 3.3: Enter the item name from the cipher data.
    logger.info("Step 3.3: Entering item name '%s'...", cipher["name"])
    name_entry = d(resourceId=CT.ITEM_NAME_ENTRY)
    if not _scroll_until_visible(d, name_entry):
        raise RuntimeError("ItemNameEntry not visible")
    wait_and_set_text(d, name_entry, cipher["name"])

    # Step 3.4: Enter the username from the cipher data.
    logger.info("Step 3.4: Entering username '%s'...", cipher["username"])
    user_entry = d(resourceId=CT.LOGIN_USERNAME_ENTRY)
    if not _scroll_until_visible(d, user_entry):
        raise RuntimeError("LoginUsernameEntry not visible")
    wait_and_set_text(d, user_entry, cipher["username"])

    # Step 3.5: Enter the password from the cipher data.
    logger.info("Step 3.5: Entering password '%s'...", cipher["password"])
    pass_entry = d(resourceId=CT.LOGIN_PASSWORD_ENTRY)
    if not _scroll_until_visible(d, pass_entry):
        raise RuntimeError("LoginPasswordEntry not visible")
    wait_and_set_text(d, pass_entry, cipher["password"])

    # Step 3.6: Enter the website URI from the cipher data.
    logger.info("Step 3.6: Entering website URI '%s'...", cipher["website"])
    uri_entry = d(resourceId=CT.LOGIN_URI_ENTRY)
    if not _scroll_until_visible(d, uri_entry):
        raise RuntimeError("LoginUriEntry not visible")
    wait_and_set_text(d, uri_entry, cipher["website"])

    # Step 3.7: Click the Save button to save the cipher.
    logger.info("Step 3.7: Clicking the Save button...")
    save_button = d(resourceId=CT.SAVE_BUTTON)
    if not _scroll_until_visible(d, save_button):
        raise RuntimeError("SaveButton not visible")
    if not click_then_expect(
        d,
        save_button,
        lambda: d(resourceId=CT.ADD_ITEM_BUTTON).exists
        or d(resourceId=CT.ALERT_POPUP).exists,
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

    if email and d(resourceId=CT.ADD_ITEM_BUTTON).exists:
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
        _complete_post_registration_setup(d)

        if d(resourceId=CT.ADD_ITEM_BUTTON).exists:
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
            if d(resourceId=CT.LOGGING_IN_AS_LABEL).exists:
                try:
                    label_text = d(resourceId=CT.LOGGING_IN_AS_LABEL).get_text()
                except Exception:
                    label_text = ""
            if email not in label_text:
                logger.info(
                    "Login screen is prefilled for a different account. Choosing 'Not you?'."
                )
                if click_then_expect(
                    d,
                    d(resourceId=CT.NOT_YOU_LABEL),
                    d(resourceId=CT.EMAIL_ADDRESS_ENTRY),
                    timeout=SHORT_WAIT,
                ):
                    wait_for_ui_stable(d, timeout=SHORT_WAIT)

        if (
            d(resourceId=CT.EMAIL_ADDRESS_ENTRY).exists
            and not d(resourceId=CT.NAME_ENTRY).exists
        ):
            logger.info("Entering email: %s...", email)
            wait_and_set_text(d, d(resourceId=CT.EMAIL_ADDRESS_ENTRY), email)

            logger.info("Clicking 'Continue'...")
            if not click_then_expect(
                d,
                d(resourceId=CT.CONTINUE_BUTTON),
                lambda: d(resourceId=CT.MASTER_PASSWORD_ENTRY).exists
                or d(resourceId=CT.ALERT_POPUP).exists,
                timeout=15,
            ):
                logger.error("Landing screen did not advance to the Login screen.")
                return False

        if not d(resourceId=CT.MASTER_PASSWORD_ENTRY).exists:
            logger.error("Master password field is not visible for %s.", email)
            return False

        _dismiss_common_popups(d)

        logger.info("Entering master password...")
        _fill_bitwarden_master_password_fields(d, password)
        wait_for_ui_stable(d, min_consecutive=2, timeout=10)

        if _vault_unlocked_visible(d):
            logger.info(
                "Vault already visible after password entry; skipping submit tap."
            )
            return True

        try:
            d.press("enter")
        except Exception:
            pass
        time.sleep(1.5)
        if _vault_unlocked_visible(d):
            logger.info("Vault reached via IME submit after master password entry.")
            return True

        on_vault_unlock = _is_vault_unlock_screen(d)
        if on_vault_unlock:
            try:
                d.press("enter")
            except Exception:
                pass
            time.sleep(1.5)
            if _vault_unlocked_visible(d):
                logger.info("Vault unlocked via IME action on vault-unlock screen.")
                return True

        _dismiss_common_popups(d)

        # --- Submitting and Verifying Outcome ---
        submit_button = _select_auth_submit_control(d)

        if submit_button is None:
            if d(resourceId=CT.CONFIRM_MASTER_PASSWORD_ENTRY).exists:
                logger.error(
                    "Registration password step is visible, but no Next/Submit/Continue "
                    "control was found after scrolling."
                )
            else:
                logger.error(
                    "Master password is visible, but neither LoginScreen nor "
                    "VaultUnlockScreen submit controls were detected."
                )
            return False

        logger.info("Submitting authentication on the current Bitwarden screen...")
        if not click_then_expect(
            d,
            submit_button,
            _auth_submit_terminal_state,
            timeout=NETWORK_WAIT + 15,
        ):
            logger.error(
                "Login submission did not produce an expected post-submit state."
            )
            return False

        # Check success first — if vault is visible, we're done regardless of overlay state
        if _vault_unlocked_visible(d):
            logger.info("Login successful. Main vault is visible.")
            return True

        # Check for real error dialogs (loading overlay has AlertProgressIndicator; skip it)
        if (
            d(resourceId=CT.ALERT_POPUP).exists
            and not d(resourceId=CT.ALERT_PROGRESS_INDICATOR).exists
        ):
            logger.warning("Error dialog detected. Dismissing...")
            _dismiss_common_popups(d)
            logger.error("Login failed due to error dialog.")
            return False

        # Success is defined by the appearance of the main vault screen's header.
        # A failed login will not proceed to this screen.
        logger.info("Verifying login outcome...")
        if d(resourceId=CT.VAULT_TAB).wait(timeout=8.0) or _vault_unlocked_visible(d):
            logger.info("Login successful. Main vault is visible.")
            return True
        else:
            # Log a quick diagnostic snapshot to aid debugging
            missing = []
            if not d(resourceId=CT.VAULT_TAB).exists:
                missing.append("VaultTab")
            if not d(resourceId=CT.ADD_ITEM_BUTTON).exists:
                missing.append("AddItemButton")
            if not d(resourceId=CT.HEADER_BAR_COMPONENT).exists:
                missing.append("HeaderBarComponent")
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
