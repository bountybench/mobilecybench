import argparse
import sys
import time
import json
from typing import Optional

import uiautomator2 as u2


def parse_args():
    parser = argparse.ArgumentParser(description="DAVx5 account setup script")
    parser.add_argument("--server-url", required=True, help="CalDAV/CardDAV server URL")
    parser.add_argument("--username", required=True, help="Username for authentication")
    parser.add_argument("--password", required=True, help="Password for authentication")
    parser.add_argument("--timeout", type=int, default=60, help="Timeout for UI operations")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    return parser.parse_args()


def log(message: str, verbose: bool = True):
    """Log message to stderr if verbose is enabled"""
    if verbose:
        print(f"[DAVx5] {message}", file=sys.stderr)


def wait_and_click_text(d: u2.Device, text: str, timeout: float = 30, verbose: bool = True) -> bool:
    """Wait for text to appear and click it"""
    if d(text=text).wait(timeout=timeout):
        log(f"Clicking text: '{text}'", verbose)
        d(text=text).click_exists(timeout=3)
        time.sleep(1.5)
        return True
    log(f"Could not find text: '{text}' within {timeout}s", verbose)
    return False


def wait_and_click_desc(d: u2.Device, desc: str, timeout: float = 30, verbose: bool = True) -> bool:
    """Wait for description to appear and click it"""
    if d(description=desc).wait(timeout=timeout):
        log(f"Clicking description: '{desc}'", verbose)
        d(description=desc).click_exists(timeout=3)
        time.sleep(1.5)
        return True
    log(f"Could not find description: '{desc}' within {timeout}s", verbose)
    return False


def wait_for_ui_stable(d: u2.Device, timeout: float = 30, interval: float = 0.5) -> bool:
    """Wait until the UI hierarchy stops changing"""
    log("Waiting for UI to stabilize")
    prev_hierarchy = None
    start = time.time()

    while time.time() - start < timeout:
        try:
            current_hierarchy = d.dump_hierarchy(compressed=True)
            if current_hierarchy == prev_hierarchy:
                return True
            prev_hierarchy = current_hierarchy
            time.sleep(interval)
        except Exception:
            time.sleep(interval)
    
    log("UI failed to stabilize within timeout")
    return False


def dismiss_dialogs(d: u2.Device, verbose: bool = True):
    """Dismiss common permission and welcome dialogs"""
    dialog_texts = [
        "ALLOW", "Allow", "OK", "Got it", "Continue", "Next", 
        "Accept", "Grant", "Permit", "Enable"
    ]
    
    for _ in range(3):  # Try multiple times
        dismissed = False
        for text in dialog_texts:
            if d(text=text).exists:
                log(f"Dismissing dialog: '{text}'", verbose)
                d(text=text).click_exists(timeout=2)
                time.sleep(1)
                dismissed = True
                break
        if not dismissed:
            break


def find_and_fill_field(d: u2.Device, field_labels: list, value: str, verbose: bool = True) -> bool:
    """Try to find and fill a text field using multiple label strategies"""
    
    # Strategy 1: Look for labels with sibling EditText
    for label in field_labels:
        if d(text=label).exists:
            log(f"Found label: '{label}', looking for sibling EditText", verbose)
            edit_field = d(text=label).sibling(className="android.widget.EditText")
            if edit_field.exists:
                log(f"Filling field via label sibling: '{label}'", verbose)
                edit_field.click()
                time.sleep(0.5)
                edit_field.clear_text()
                edit_field.set_text(value)
                time.sleep(0.5)
                return True
    
    # Strategy 2: Look for hint text in EditText fields
    for label in field_labels:
        if d(className="android.widget.EditText", text=label).exists:
            log(f"Found EditText with hint: '{label}'", verbose)
            field = d(className="android.widget.EditText", text=label)
            field.click()
            time.sleep(0.5)
            field.clear_text()
            field.set_text(value)
            time.sleep(0.5)
            return True
    
    # Strategy 3: Look for resourceId containing field keywords
    for label in field_labels:
        keyword = label.lower().replace(" ", "").replace("-", "")
        try:
            if d(className="android.widget.EditText", resourceIdMatches=f".*{keyword}.*").exists:
                log(f"Found EditText by resourceId pattern: '{keyword}'", verbose)
                field = d(className="android.widget.EditText", resourceIdMatches=f".*{keyword}.*")
                field.click()
                time.sleep(0.5)
                field.clear_text()
                field.set_text(value)
                time.sleep(0.5)
                return True
        except Exception:
            continue
    
    log(f"Could not find field for labels: {field_labels}", verbose)
    return False


def setup_davx5_account(server_url: str, username: str, password: str, timeout: int = 60, verbose: bool = True) -> bool:
    """Main function to set up DAVx5 account"""
    
    try:
        d = u2.connect()
        log("Connected to device", verbose)
    except Exception as e:
        log(f"Could not connect to device: {e}", verbose)
        return False
    
    # Launch DAVx5
    log("Launching DAVx5", verbose)
    d.app_start("at.bitfire.davdroid")
    time.sleep(3)
    
    # Dismiss any initial dialogs
    dismiss_dialogs(d, verbose)
    wait_for_ui_stable(d, timeout=10)
    
    # Look for account setup entry points
    setup_options = [
        "Add account", "ADD ACCOUNT", "Create account", "Set up account",
        "+", "Add", "New account", "Login", "Sign in", "Configure"
    ]
    
    account_added = False
    for option in setup_options:
        if d(text=option).exists:
            log(f"Found setup option: '{option}'", verbose)
            d(text=option).click()
            time.sleep(2)
            wait_for_ui_stable(d)
            account_added = True
            break
    
    if not account_added:
        # Try floating action button or plus icon
        if d(description="Add").exists or d(className="android.widget.ImageButton").exists:
            log("Trying floating action button", verbose)
            if d(description="Add").exists:
                d(description="Add").click()
            else:
                d(className="android.widget.ImageButton").click()
            time.sleep(2)
            wait_for_ui_stable(d)
            account_added = True
    
    if not account_added:
        log("Could not find account setup option", verbose)
        return False
    
    # Look for DAV account type selection
    dav_options = [
        "Login with URL and user name", "CalDAV/CardDAV", "CalDAV", "CardDAV", "WebDAV", "DAV",
        "Manual setup", "Advanced", "Other"
    ]
    
    for option in dav_options:
        if wait_and_click_text(d, option, timeout=5, verbose=verbose):
            wait_for_ui_stable(d)
            break
    
    # Fill server URL
    server_labels = [
        "Server URL", "Base URL", "URL", "Server", "Host", 
        "Server address", "CalDAV URL", "CardDAV URL"
    ]
    
    if not find_and_fill_field(d, server_labels, server_url, verbose):
        log("Could not fill server URL field", verbose)
        return False
    
    # Fill username
    username_labels = [
        "Username", "User name", "Login", "Email", "Account", 
        "User", "Login name", "Account name"
    ]
    
    if not find_and_fill_field(d, username_labels, username, verbose):
        log("Could not fill username field", verbose)
        return False
    
    # Fill password
    password_labels = [
        "Password", "Pass", "Authentication", "Secret", "Credentials"
    ]
    
    if not find_and_fill_field(d, password_labels, password, verbose):
        log("Could not fill password field", verbose)
        return False
    
    # Submit/Connect
    submit_options = [
        "CONNECT", "Connect", "LOGIN", "Login", "Sign in", "SIGN IN",
        "Add account", "CREATE", "Create", "SAVE", "Save", "NEXT", "Next",
        "Test connection", "Verify", "Continue"
    ]
    
    submitted = False
    for option in submit_options:
        if wait_and_click_text(d, option, timeout=5, verbose=verbose):
            submitted = True
            break
    
    if not submitted:
        log("Could not find submit button", verbose)
        return False
    
    # Wait for connection result
    log("Waiting for connection result...", verbose)
    time.sleep(5)
    wait_for_ui_stable(d, timeout=15)
    
    # Check for success indicators
    hierarchy = d.dump_hierarchy()
    success_indicators = [
        "success", "connected", "account added", "synchronization", 
        "calendars", "contacts", "setup complete"
    ]
    
    failure_indicators = [
        "error", "failed", "unable", "connection", "authentication", 
        "invalid", "unauthorized", "timeout"
    ]
    
    hierarchy_lower = hierarchy.lower()
    
    # Check for failure first
    for indicator in failure_indicators:
        if indicator in hierarchy_lower:
            log(f"Connection failed - found failure indicator: '{indicator}'", verbose)
            return False
    
    # Check for success
    for indicator in success_indicators:
        if indicator in hierarchy_lower:
            log(f"Connection successful - found success indicator: '{indicator}'", verbose)
            return True
    
    # If no clear indicators, assume success if no obvious error dialogs
    if "error" not in hierarchy_lower and "failed" not in hierarchy_lower:
        log("No clear failure indicators found, assuming success", verbose)
        return True
    
    log("Could not determine connection status", verbose)
    if verbose:
        log("UI hierarchy for debugging:", verbose)
        print(hierarchy[:1000], file=sys.stderr)  # Print first 1000 chars for debugging
    
    return False


def main():
    args = parse_args()
    
    success = setup_davx5_account(
        args.server_url, 
        args.username, 
        args.password, 
        args.timeout,
        args.verbose
    )
    
    if success:
        log("✅ DAVx5 account setup successful", args.verbose)
        sys.exit(0)
    else:
        log("❌ DAVx5 account setup failed", args.verbose)
        sys.exit(1)


if __name__ == "__main__":
    main()