"""
Canonical Bitwarden Android UI identifiers for automation.

**Source of truth:** the app submodule at ``apps/bitwarden/codebase`` (this repo).

- **Compose testTags** — search ``Modifier.testTag("…")`` / ``testTag(tag = "…")`` under
  ``codebase/app/src/main/kotlin`` and ``codebase/ui/src/main/kotlin``.
- **Visible text / contentDescription fallbacks** — default (English) copy from
  ``codebase/app/src/main/res/values/strings.xml`` (``R.string.*``). CI uses English; other
  locales need different literals or tag-only selectors.

When Bitwarden changes a tag or string, update this module and ``bw_workflows.py`` together.

Screen logic worth keeping aligned with Kotlin:

- ``CreateAccountScreen`` — email + passwords + **toolbar** ``SubmitButton`` (no bottom ``Next``).
- ``CompleteRegistrationScreen`` — passwords + hint + breach toggle + bottom CTA labeled
  ``R.string.next`` (no ``testTag`` on that button); ``validSubmissionReady`` requires both
  password fields (see ``CompleteRegistrationViewModel`` / ``CompleteRegistrationState``).
- ``LoginScreen`` — ``MasterPasswordEntry``, ``LogInWithMasterPasswordButton``, etc.
- ``VaultUnlockScreen`` — ``UnlockVaultButton`` when input visible.
"""

from __future__ import annotations


class ComposeTags:
    """Values must match Compose ``testTag`` strings in ``apps/bitwarden/codebase``."""

    ACCOUNT_CELL = "AccountCell"
    ACCOUNT_EMAIL_LABEL = "AccountEmailLabel"
    ACCOUNT_LIST_VIEW = "AccountListView"
    ACTIVE_VAULT_ICON = "ActiveVaultIcon"
    ADD_ACCOUNT_BUTTON = "AddAccountButton"
    ADD_ITEM_BUTTON = "AddItemButton"
    ACCEPT_ALERT_BUTTON = "AcceptAlertButton"
    # contentDescription on TermsAndPrivacySwitch — CreateAccountScreen.kt
    ACCEPT_POLICIES_TOGGLE = "AcceptPoliciesToggle"
    ALERT_POPUP = "AlertPopup"
    ALERT_PROGRESS_INDICATOR = "AlertProgressIndicator"
    ALERT_SELECTION_OPTION = "AlertSelectionOption"
    CHOOSE_ACCOUNT_CREATION_BUTTON = "ChooseAccountCreationButton"
    CHOOSE_LOGIN_BUTTON = "ChooseLoginButton"
    CONFIRM_MASTER_PASSWORD_ENTRY = "ConfirmMasterPasswordEntry"
    CONTINUE_BUTTON = "ContinueButton"
    CREATE_ACCOUNT_LABEL = "CreateAccountLabel"
    CURRENT_ACTIVE_ACCOUNT = "CurrentActiveAccount"
    EMAIL_ADDRESS_ENTRY = "EmailAddressEntry"
    HEADER_BAR_COMPONENT = "HeaderBarComponent"
    ITEM_NAME_ENTRY = "ItemNameEntry"
    LOGGING_IN_AS_LABEL = "LoggingInAsLabel"
    LOGIN_PASSWORD_ENTRY = "LoginPasswordEntry"
    LOGIN_URI_ENTRY = "LoginUriEntry"
    LOGIN_USERNAME_ENTRY = "LoginUsernameEntry"
    LOG_IN_WITH_MASTER_PASSWORD_BUTTON = "LogInWithMasterPasswordButton"
    MASTER_PASSWORD_ENTRY = "MasterPasswordEntry"
    NAME_ENTRY = "NameEntry"
    NOT_YOU_LABEL = "NotYouLabel"
    OPEN_EMAIL_APP = "OpenEmailApp"
    REGION_SELECTOR_DROPDOWN = "RegionSelectorDropdown"
    SAVE_BUTTON = "SaveButton"
    SERVER_URL_ENTRY = "ServerUrlEntry"
    SET_UP_LATER_BUTTON = "SetUpLaterButton"
    SUBMIT_BUTTON = "SubmitButton"
    UNLOCK_VAULT_BUTTON = "UnlockVaultButton"
    VAULT_TAB = "VaultTab"


class StringsEn:
    """
    Default English UI strings from ``values/strings.xml`` (``R.string.*``).

    Used when automation matches visible text or ``contentDescription``. Not a substitute
    for Compose tags where those exist.
    """

    ACCOUNT = "Account"  # R.string.account
    CONFIRM = "Confirm"  # R.string.confirm
    CONTINUE = "Continue"  # R.string.continue_text
    CREATE_AN_ACCOUNT = "Create an account"  # R.string.create_an_account
    LOCK = "Lock"  # R.string.lock
    LOG_IN_WITH_MASTER_PASSWORD = (
        "Log in with master password"  # R.string.log_in_with_master_password
    )
    LOG_OUT = "Log out"  # R.string.log_out
    MORE = "More"  # R.string.more
    NEXT = "Next"  # R.string.next
    REMOVE_ACCOUNT = "Remove account"  # R.string.remove_account
    SELF_HOSTED = "Self-hosted"  # R.string.self_hosted
    TURN_ON_LATER = "Turn on later"  # R.string.turn_on_later
    TYPE_LOGIN = "Login"  # R.string.type_login (cipher type in add-item sheet)
    UNLOCK = "Unlock"  # R.string.unlock
    YES = "Yes"  # R.string.yes


# Substring fallback when full ``LOG_IN_WITH_MASTER_PASSWORD`` text is ellipsized in hierarchy.
LOG_IN_WITH_MASTER_PASSWORD_TEXT_PREFIX = "Log in with master"
