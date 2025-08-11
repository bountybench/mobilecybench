"""
Bitwarden-specific UI workflows built on top of generic ui_utils primitives.

These functions orchestrate common Bitwarden flows such as initial setup,
account creation, cipher creation, logging out, and attempting login.
"""

import sys
import time

from ui_utils import wait_and_click, wait_and_set_text
from util import BITWARDEN_PKG, SERVER_URL


def bw_initialize_local_host(d):
    """
    Initializes the device connection and launches the Bitwarden app
    """
    # --- Step 1: App Initialization and Server Configuration ---
    # The following steps launch the application and point it to the
    # self-hosted Vaultwarden server instance.

    # --- 1.1: App Launch ---
    print(f"Step 1.1.1: Stopping any existing instances of {BITWARDEN_PKG}...")
    d.app_stop(BITWARDEN_PKG)
    time.sleep(1)  # Give it a moment to release resources

    print(f"Step 1.1.2: Launching {BITWARDEN_PKG}...")
    d.app_start(BITWARDEN_PKG, use_monkey=True)

    # Step 1.2.1: Click the "Create account" button on the welcome screen
    print("Step 1.2.1: Clicking 'Account creation'...")
    wait_and_click(d, d(resourceId="ChooseAccountCreationButton"))

    # Step 1.2.2: Click the region selector dropdown to configure a self-hosted server
    print("Step 1.2.2: Opening self-hosted server configuration...")
    wait_and_click(d, d(resourceId="RegionSelectorDropdown"))

    # Step 1.2.3: Select the "Self-hosted" option from the dialog
    print("Step 1.2.3: Selecting 'Self-hosted' option...")
    wait_and_click(d, d(text="Self-hosted"))

    # Step 1.2.4: Enter the self-hosted server URL
    print(f"Step 1.2.4: Entering server URL: {SERVER_URL}...")
    wait_and_set_text(d, d(resourceId="ServerUrlEntry"), SERVER_URL)

    # Step 1.2.5: Click the Save button to save the server configuration
    print("Step 1.2.5: Saving server configuration...")
    wait_and_click(d, d(resourceId="SaveButton"))


def bw_make_account(d, email, name, master_password, account_index=0):
    """
    Creates a Bitwarden account with the specified credentials
    """
    # --- Step 2: User Account Creation ---
    # The following steps walk through the UI to register a new user
    # with the provided credentials.
    print(f"[INFO] Creating account for {email}")

    # Step 2.0: Click on the "Create account" button only if not the first account
    if account_index > 0:
        print("Step 2.0: Clicking on 'Create account' button...")
        wait_and_click(d, d(resourceId="CreateAccountLabel"))
    else:
        print("Step 2.0: Skipping 'Create account' button (first account)...")

    # Step 2.1: Enter the email address
    print(f"Step 2.1: Entering email address: {email}...")
    wait_and_set_text(d, d(resourceId="EmailAddressEntry"), email)

    # Step 2.2: Enter the user's name
    print(f"Step 2.2: Entering name: {name}...")
    wait_and_set_text(d, d(resourceId="NameEntry"), name)

    # Step 2.3: Click the Continue button to proceed with account creation
    print("Step 2.3: Clicking Continue button...")
    wait_and_click(d, d(resourceId="ContinueButton"))

    # Step 2.4: Enter the master password
    print(f"Step 2.4: Entering master password: {master_password}...")
    wait_and_set_text(d, d(resourceId="MasterPasswordEntry"), master_password)

    # Step 2.5: Enter the master password confirmation
    print(f"Step 2.5: Entering master password confirmation: {master_password}...")
    wait_and_set_text(d, d(resourceId="ConfirmMasterPasswordEntry"), master_password)

    # Step 2.6: Click the Next button to proceed with account creation
    print("Step 2.6: Clicking Next button...")
    wait_and_click(d, d(text="Next"))

    # Step 2.7: Click "Set up later" to skip unlock setup
    print("Step 2.7: Clicking 'Set up later' to skip unlock setup...")
    wait_and_click(d, d(resourceId="SetUpLaterButton"))

    # Step 2.8: Click "Confirm" to confirm skipping unlock setup
    print("Step 2.8: Clicking 'Confirm' to confirm skipping unlock setup...")
    wait_and_click(d, d(resourceId="AcceptAlertButton"))

    # Step 2.9: Click "Turn on later" to skip autofill setup
    print("Step 2.9: Clicking 'Turn on later' to skip autofill setup...")
    wait_and_click(d, d(text="Turn on later"))

    # Step 2.10: Click "Confirm" to confirm skipping autofill setup
    print("Step 2.10: Clicking 'Confirm' to confirm skipping autofill setup...")
    wait_and_click(d, d(resourceId="AcceptAlertButton"))

    # Step 2.11: Click the Continue button to complete account setup
    print("Step 2.11: Clicking Continue button to complete account setup...")
    wait_and_click(d, d(text="Continue"))

    print(f"[INFO] Account for {email} created successfully")


def bw_create_new_cipher(d, cipher):
    """
    Creates a new cipher entry in the vault
    """
    # --- Step 3: Cipher Creation ---
    # The following steps create a new login cipher in the user's vault.
    print(f"[INFO] Creating cipher: {cipher['name']}")

    # Step 3.1: Click the main '+' button to add a new item.
    print("Step 3.1: Clicking the 'Add Item' button...")
    wait_and_click(d, d(resourceId="AddItemButton"))

    # Step 3.2: Select "Login" from the item type dialog.
    print("Step 3.2: Selecting 'Login' as the item type...")
    wait_and_click(d, d(resourceId="AlertSelectionOption", text="Login"))

    # Handle the optional "Bitwarden Autofill Service" dialog that may appear.
    print("Step 3.2: Checking for Autofill Service dialog...")
    if d(resourceId="AcceptAlertButton").exists(timeout=1):
        print("Step 3.2: Autofill dialog found. Clicking 'Okay'...")
        wait_and_click(d, d(resourceId="AcceptAlertButton"))

    # Step 3.3: Enter the item name from the cipher data.
    print(f"Step 3.3: Entering item name '{cipher['name']}'...")
    wait_and_set_text(d, d(resourceId="ItemNameEntry"), cipher["name"])

    # Step 3.4: Enter the username from the cipher data.
    print(f"Step 3.4: Entering username '{cipher['username']}'...")
    wait_and_set_text(d, d(resourceId="LoginUsernameEntry"), cipher["username"])

    # Step 3.5: Enter the password from the cipher data.
    print(f"Step 3.5: Entering password '{cipher['password']}'...")
    wait_and_set_text(d, d(resourceId="LoginPasswordEntry"), cipher["password"])

    # Step 3.6: Enter the website URI from the cipher data.
    print(f"Step 3.6: Entering website URI '{cipher['website']}'...")
    wait_and_set_text(d, d(resourceId="LoginUriEntry"), cipher["website"])

    # Step 3.7: Click the Save button to save the cipher.
    print("Step 3.7: Clicking the Save button...")
    wait_and_click(d, d(resourceId="SaveButton"))

    print(f"[INFO] Finished creating cipher: {cipher['name']}")


def bw_lock_and_logout(d):
    """
    Locks the vault and logs out
    """
    print("[INFO] Locking and logging out")

    # Step 4.1: Click the main options button in the header bar
    print("Step 4.1: Clicking header options button...")
    wait_and_click(d, d(resourceId="HeaderBarOptionsButton"))

    # Step 4.2: Click on "Lock" to lock the vault
    print("Step 4.2: Clicking 'Lock' to lock the vault...")
    wait_and_click(d, d(text="Lock"))

    # Step 4.3: Click the header bar options button again
    print("Step 4.3: Clicking header bar options button...")
    wait_and_click(d, d(resourceId="HeaderBarOptionsButton"))

    # Step 4.4: Click on "Log out" (FloatingOptionsItem)
    print("Step 4.4: Clicking 'Log out' (FloatingOptionsItem)...")
    wait_and_click(d, d(resourceId="FloatingOptionsItem"))

    # Step 4.5: Click "Yes" to confirm logout (AcceptAlertButton)
    print("Step 4.5: Clicking 'Yes' to confirm logout (AcceptAlertButton)...")
    wait_and_click(d, d(resourceId="AcceptAlertButton"))

    print("[INFO] Locking and logging out complete")


def bw_attempt_login(d, email, password):
    """
    Attempts to login to the Bitwarden app
    """
    try:
        # --- Stop any previous instances and start fresh ---
        print(f"Stopping any existing instances of {BITWARDEN_PKG}...")
        d.app_stop(BITWARDEN_PKG)
        time.sleep(1)
        print(f"Launching {BITWARDEN_PKG}...")
        d.app_start(BITWARDEN_PKG, use_monkey=True)

        # --- Wait for the app to load ---
        print("Waiting for app to load...")
        time.sleep(3)  # Give app time to fully load

        # Check for error dialogs first and dismiss them
        if d(resourceId="AlertPopup").exists:
            print("Error dialog detected on app start. Dismissing...")
            wait_and_click(d, d(resourceId="AcceptAlertButton"))
            time.sleep(2)

        # Wait for either email entry (initial login) or master password entry (locked vault)
        if not (
            d(resourceId="EmailAddressEntry").exists
            or d(resourceId="MasterPasswordEntry").exists
        ):
            print(
                "No email or master password entry found. Waiting for one to appear..."
            )
            # If neither exists immediately, wait for one to appear
            d(resourceId="EmailAddressEntry").wait(timeout=10.0) or d(
                resourceId="MasterPasswordEntry"
            ).wait(timeout=10.0)

        # --- Check if vault is locked and handle accordingly ---
        print("Checking if vault is locked...")
        if d(text="Unlock").exists:
            print("Vault is locked. Clicking HeaderBarOptionsButton...")
            wait_and_click(d, d(resourceId="HeaderBarOptionsButton"))

            print("Clicking logout")
            wait_and_click(d, d(resourceId="FloatingOptionsItem"))

            print("Accepting alert")
            wait_and_click(d, d(resourceId="AcceptAlertButton"))

            # Wait for the app to return to the initial login screen
            print("Waiting for app to return to login screen...")
            time.sleep(3)

        # --- Entering Credentials ---
        print("Vault is unlocked. Entering credentials...")
        print(f"Entering email: {email}...")
        wait_and_set_text(d, d(resourceId="EmailAddressEntry"), email)

        print("Clicking 'Continue'...")
        wait_and_click(d, d(resourceId="ContinueButton"))

        print("Entering master password...")
        wait_and_set_text(d, d(resourceId="MasterPasswordEntry"), password)

        # --- Submitting and Verifying Outcome ---
        print("Clicking 'Unlock' to log in...")
        wait_and_click(d, d(resourceId="LogInWithMasterPasswordButton"))

        # Check for error dialogs first
        if d(resourceId="AlertPopup").exists:
            print("Error dialog detected. Dismissing...")
            wait_and_click(d, d(resourceId="AcceptAlertButton"))
            time.sleep(1)
            print("Login failed due to error dialog.")
            return False

        # Success is defined by the appearance of the main vault screen's header.
        # A failed login will not proceed to this screen.
        print("Verifying login outcome...")
        if d(resourceId="VaultTab").wait(timeout=5.0):
            print("[SUCCESS] Login successful. Main vault is visible.")
            return True
        else:
            print("Main vault not visible after timeout.")
            return False

    except Exception as e:
        print(
            f"[ERROR] An unexpected error occurred during UI automation: {e}",
            file=sys.stderr,
        )
        # Dump the UI hierarchy to the console for debugging
        print(d.dump_hierarchy(), file=sys.stderr)
        return False
