"""
Bitwarden-specific UI workflows built on top of generic ui_utils primitives.

These functions orchestrate common Bitwarden flows such as initial setup,
account creation, cipher creation, logging out, and attempting login.
"""

import logging
import os
import sys

from utils.ui_utils import wait_and_click, wait_and_set_text, wait_for_ui_stable

from .util import BITWARDEN_PKG, SERVER_URL

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
logger = logging.getLogger("mobilecybench.bitwarden.workflows")
logger.setLevel(os.getenv("BITWARDEN_LOG_LEVEL", "INFO"))
_handler = logging.StreamHandler(stream=sys.stderr)
_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logger.handlers[:] = [_handler]
logger.propagate = False


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

    # Step 1.2.1: Click the "Create account" button on the welcome screen
    logger.info("Step 1.2.1: Clicking 'Account creation'...")
    # Add an explicit wait for the button to appear to improve robustness
    d(resourceId="ChooseAccountCreationButton").wait(timeout=10.0)
    wait_and_click(d, d(resourceId="ChooseAccountCreationButton"))

    # Step 1.2.2: Click the region selector dropdown to configure a self-hosted server
    logger.info("Step 1.2.2: Opening self-hosted server configuration...")
    wait_and_click(d, d(resourceId="RegionSelectorDropdown"))

    # Step 1.2.3: Select the "Self-hosted" option from the dialog
    logger.info("Step 1.2.3: Selecting 'Self-hosted' option...")
    wait_and_click(d, d(text="Self-hosted"))

    # Step 1.2.4: Enter the self-hosted server URL
    logger.info("Step 1.2.4: Entering server URL: %s...", SERVER_URL)
    wait_and_set_text(d, d(resourceId="ServerUrlEntry"), SERVER_URL)

    # Step 1.2.5: Click the Save button to save the server configuration
    logger.info("Step 1.2.5: Saving server configuration...")
    wait_and_click(d, d(resourceId="SaveButton"))


def bw_make_account(d, email, name, master_password, account_index=0):
    """
    Creates a Bitwarden account with the specified credentials
    """
    # --- Step 2: User Account Creation ---
    # The following steps walk through the UI to register a new user
    # with the provided credentials.
    logger.info("Creating account for %s", email)

    # Step 2.0: Click on the "Create account" button only if not the first account
    if account_index > 0:
        logger.info("Step 2.0: Clicking on 'Create account' button...")
        wait_and_click(d, d(resourceId="CreateAccountLabel"))
    else:
        logger.info("Step 2.0: Skipping 'Create account' button (first account)...")

    # Step 2.1: Enter the email address
    logger.info("Step 2.1: Entering email address: %s...", email)
    wait_and_set_text(d, d(resourceId="EmailAddressEntry"), email)

    # Step 2.2: Enter the user's name
    logger.info("Step 2.2: Entering name: %s...", name)
    wait_and_set_text(d, d(resourceId="NameEntry"), name)

    # Step 2.3: Click the Continue button to proceed with account creation
    logger.info("Step 2.3: Clicking Continue button...")
    wait_and_click(d, d(resourceId="ContinueButton"))

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
    wait_and_click(d, d(text="Next"))

    # Step 2.7: Click "Set up later" to skip unlock setup
    logger.info("Step 2.7: Clicking 'Set up later' to skip unlock setup...")
    wait_and_click(d, d(resourceId="SetUpLaterButton"))

    # Step 2.8: Click "Confirm" to confirm skipping unlock setup
    logger.info("Step 2.8: Clicking 'Confirm' to confirm skipping unlock setup...")
    wait_and_click(d, d(resourceId="AcceptAlertButton"))

    # Step 2.9: Click "Turn on later" to skip autofill setup
    logger.info("Step 2.9: Clicking 'Turn on later' to skip autofill setup...")
    wait_and_click(d, d(text="Turn on later"))

    # Step 2.10: Click "Confirm" to confirm skipping autofill setup
    logger.info("Step 2.10: Clicking 'Confirm' to confirm skipping autofill setup...")
    wait_and_click(d, d(resourceId="AcceptAlertButton"))

    # Step 2.11: Click the Continue button to complete account setup
    logger.info("Step 2.11: Clicking Continue button to complete account setup...")
    wait_and_click(d, d(text="Continue"))

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
    wait_and_click(d, d(resourceId="AddItemButton"))

    # Step 3.2: Select "Login" from the item type dialog.
    logger.info("Step 3.2: Selecting 'Login' as the item type...")
    wait_and_click(d, d(resourceId="AlertSelectionOption", text="Login"))

    # Handle the optional "Bitwarden Autofill Service" dialog that may appear.
    logger.info("Step 3.2: Checking for Autofill Service dialog...")
    if d(resourceId="AcceptAlertButton").exists(timeout=1):
        logger.info("Step 3.2: Autofill dialog found. Clicking 'Okay'...")
        wait_and_click(d, d(resourceId="AcceptAlertButton"))

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
    wait_and_click(d, d(resourceId="SaveButton"))

    logger.info("Finished creating cipher: %s", cipher["name"])


def bw_lock_and_logout(d):
    """
    Locks the vault and logs out
    """
    logger.info("Locking and logging out")

    # Step 4.1: Click the main options button in the header bar
    logger.info("Step 4.1: Clicking header options button...")
    wait_and_click(d, d(resourceId="HeaderBarOptionsButton"))

    # Step 4.2: Click on "Lock" to lock the vault
    logger.info("Step 4.2: Clicking 'Lock' to lock the vault...")
    wait_and_click(d, d(text="Lock"))

    # Step 4.3: Click the header bar options button again
    logger.info("Step 4.3: Clicking header bar options button...")
    wait_and_click(d, d(resourceId="HeaderBarOptionsButton"))

    # Step 4.4: Click on "Log out" (FloatingOptionsItem)
    logger.info("Step 4.4: Clicking 'Log out' (FloatingOptionsItem)...")
    wait_and_click(d, d(resourceId="FloatingOptionsItem"))

    # Step 4.5: Click "Yes" to confirm logout (AcceptAlertButton)
    logger.info("Step 4.5: Clicking 'Yes' to confirm logout (AcceptAlertButton)...")
    wait_and_click(d, d(resourceId="AcceptAlertButton"))

    logger.info("Locking and logging out complete")


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

        # Check for error dialogs first and dismiss them (non-fatal, with settle)
        if d(resourceId="AlertPopup").exists and d(
            resourceId="AcceptAlertButton"
        ).exists(timeout=2):
            logger.warning("Error dialog detected on app start. Dismissing...")
            wait_and_click(
                d, d(resourceId="AcceptAlertButton"), timeout=5
            )

        # Wait for either email entry (initial login) or master password entry (locked vault)
        if not (
            d(resourceId="EmailAddressEntry").exists
            or d(resourceId="MasterPasswordEntry").exists
        ):
            logger.info(
                "No email or master password entry found. Waiting for one to appear..."
            )
            # If neither exists immediately, wait for one to appear
            d(resourceId="EmailAddressEntry").wait(timeout=10.0) or d(
                resourceId="MasterPasswordEntry"
            ).wait(timeout=10.0)

        # --- Check if vault is locked and handle accordingly ---
        logger.info("Checking if vault is locked...")
        if d(text="Unlock").exists:
            logger.info("Vault is locked. Clicking HeaderBarOptionsButton...")
            wait_and_click(d, d(resourceId="HeaderBarOptionsButton"))

            logger.info("Clicking logout")
            wait_and_click(d, d(resourceId="FloatingOptionsItem"))

            logger.info("Accepting alert")
            wait_and_click(d, d(resourceId="AcceptAlertButton"))

            # Wait for the app to return to the initial login screen
            logger.info("Waiting for app to return to login screen...")
            d(resourceId="EmailAddressEntry").wait(timeout=10.0)

        # --- Entering Credentials ---
        logger.info("Vault is unlocked. Entering credentials...")
        logger.info("Entering email: %s...", email)
        wait_and_set_text(d, d(resourceId="EmailAddressEntry"), email)

        logger.info("Clicking 'Continue'...")
        wait_and_click(d, d(resourceId="ContinueButton"))

        logger.info("Entering master password...")
        wait_and_set_text(d, d(resourceId="MasterPasswordEntry"), password)

        # --- Submitting and Verifying Outcome ---
        logger.info("Clicking 'Unlock' to log in...")
        wait_and_click(d, d(resourceId="LogInWithMasterPasswordButton"))

        # Check for error dialogs first (non-fatal dismissal + settle)
        if d(resourceId="AlertPopup").exists and d(
            resourceId="AcceptAlertButton"
        ).exists(timeout=2):
            logger.warning("Error dialog detected. Dismissing...")
            wait_and_click(
                d, d(resourceId="AcceptAlertButton"), timeout=5
            )
            logger.error("Login failed due to error dialog.")
            return False

        # Success is defined by the appearance of the main vault screen's header.
        # A failed login will not proceed to this screen.
        logger.info("Verifying login outcome...")
        # Success indicators: Vault tab, HeaderBar, PageTitleLabel 'My vault'
        if (
            d(resourceId="VaultTab").wait(timeout=5.0)
            or d(resourceId="HeaderBarComponent").exists
            or d(resourceId="PageTitleLabel", text="My vault").exists
        ):
            logger.info("Login successful. Main vault is visible.")
            return True
        else:
            # Log a quick diagnostic snapshot to aid debugging
            missing = []
            if not d(resourceId="VaultTab").exists:
                missing.append("VaultTab")
            if not d(resourceId="HeaderBarComponent").exists:
                missing.append("HeaderBarComponent")
            if not d(resourceId="PageTitleLabel", text="My vault").exists:
                missing.append("PageTitleLabel/My vault")
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
