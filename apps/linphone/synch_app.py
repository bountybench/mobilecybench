import argparse
import sys
import time

import uiautomator2 as u2

parser = argparse.ArgumentParser(description="Linphone SIP account login")
parser.add_argument("--username", required=True, help="SIP username")
parser.add_argument("--password", required=True, help="SIP password")
parser.add_argument("--domain", default="10.0.2.2", help="SIP domain/server")
parser.add_argument(
    "--transport", default="TCP", help="Transport protocol (UDP/TCP/TLS)"
)
args = parser.parse_args()

username = args.username
password = args.password
domain = args.domain
transport = args.transport

d = u2.connect()


def wait_and_click_text(text, timeout=60):
    """Click on element with specific text"""
    if d(text=text).wait(timeout=timeout):
        print(f"Found and clicking: {text}", file=sys.stderr)
        d(text=text).click_exists(timeout=3)
    else:
        print(
            f"[ERROR] Could not find text: '{text}' within {timeout}s", file=sys.stderr
        )
        print(d.dump_hierarchy(), file=sys.stderr)
        exit(1)
    wait_for_ui_stable(timeout=5)


def wait_and_click_desc(desc, timeout=60):
    """Click on element with specific description"""
    if d(description=desc).wait(timeout=timeout):
        print(f"Found and clicking: {desc}", file=sys.stderr)
        d(description=desc).click_exists(timeout=3)
    else:
        print(
            f"[ERROR] Could not find description: '{desc}' within {timeout}s",
            file=sys.stderr,
        )
        print(d.dump_hierarchy(), file=sys.stderr)
        exit(1)
    wait_for_ui_stable(timeout=5)


def wait_and_click_resource_id(resource_id, timeout=60):
    """Click on element with specific resource ID"""
    if d(resourceId=resource_id).wait(timeout=timeout):
        print(f"Found and clicking resource ID: {resource_id}", file=sys.stderr)
        d(resourceId=resource_id).click_exists(timeout=3)
    else:
        print(
            f"[ERROR] Could not find resource ID: '{resource_id}' within {timeout}s",
            file=sys.stderr,
        )
        print(d.dump_hierarchy(), file=sys.stderr)
        exit(1)
    wait_for_ui_stable(timeout=5)


def wait_for_ui_stable(timeout=60, interval=0.5):
    """Wait until the UI hierarchy stops changing"""
    print("Waiting for UI to stabilize...", file=sys.stderr)
    prev_hierarchy = None
    start = time.time()
    stable_count = 0
    required_stable_checks = 2

    while time.time() - start < timeout:
        current_hierarchy = d.dump_hierarchy(compressed=True)
        if current_hierarchy == prev_hierarchy:
            stable_count += 1
            if stable_count >= required_stable_checks:
                print(
                    f"UI stabilized after {stable_count} consecutive checks",
                    file=sys.stderr,
                )
                return True
        else:
            stable_count = 0
        prev_hierarchy = current_hierarchy
        time.sleep(interval)
    print(f"UI unstable! Timed out after {timeout}s", file=sys.stderr)
    return False


def fill_text_field(label_text, value, possible_labels=None):
    """Fill a text field identified by its label"""
    if possible_labels is None:
        possible_labels = [label_text]
    else:
        possible_labels = [label_text] + possible_labels

    field_found = False
    for label in possible_labels:
        print(f"Looking for field: '{label}'", file=sys.stderr)
        label_elem = d(text=label)
        if label_elem.wait(timeout=10):
            print(f"Found field: '{label}'", file=sys.stderr)
            # Try to find sibling EditText
            edit = label_elem.sibling(className="android.widget.EditText")
            if edit.exists():
                edit.click()
                time.sleep(1)
                edit.set_text(value)
                d.press("enter")
                time.sleep(1)
                field_found = True
                break

    if not field_found:
        print(
            f"[ERROR] Could not find field with labels: {possible_labels}",
            file=sys.stderr,
        )
        print(d.dump_hierarchy(), file=sys.stderr)
        exit(1)


def check_registration_status():
    """Check if the account is registered successfully"""
    print("Checking registration status...", file=sys.stderr)
    time.sleep(5)  # Wait for registration

    hierarchy = d.dump_hierarchy()

    # Check for success indicators
    success_indicators = ["Registered", "Connected", "Online"]
    error_indicators = ["Error", "Failed", "Not registered", "Connection failed"]

    for indicator in success_indicators:
        if indicator in hierarchy:
            print(f"[SUCCESS] Found success indicator: {indicator}", file=sys.stderr)
            return True

    for indicator in error_indicators:
        if indicator in hierarchy:
            print(f"[ERROR] Found error indicator: {indicator}", file=sys.stderr)
            return False

    print("[WARNING] Could not determine registration status", file=sys.stderr)
    return None


# Main automation flow
print(f"Starting Linphone login automation for {username}@{domain}", file=sys.stderr)
wait_for_ui_stable(timeout=30, interval=1)

# Check if we're on a welcome/first-launch screen
if d(text="Register an account").exists(timeout=5):
    print(
        "Welcome screen detected, looking for 'Use a SIP account' option",
        file=sys.stderr,
    )

    # Try to find and click "Use a SIP account" or similar
    if d(text="Use a SIP account").exists(timeout=5):
        wait_and_click_text("Use a SIP account")
    elif d(text="Use SIP account").exists(timeout=5):
        wait_and_click_text("Use SIP account")
    elif d(textContains="already have").exists(timeout=5):
        d(textContains="already have").click()
        wait_for_ui_stable(timeout=5)
    elif d(text="Skip").exists(timeout=5):
        wait_and_click_text("Skip")
    else:
        print("[ERROR] Cannot find option to use existing SIP account", file=sys.stderr)
        print(d.dump_hierarchy(), file=sys.stderr)
        exit(1)

# Check if we're already on the login screen
if d(resourceId="org.linphone:id/login", text="Login").exists(timeout=5):
    print("Already on login screen, skipping navigation", file=sys.stderr)
else:
    # Step 1: Open the sidebar menu using the exact resource ID
    print("Opening sidebar menu...", file=sys.stderr)

    drawer_button = d(
        resourceId="org.linphone:id/drawer_menu", className="android.widget.ImageView"
    )
    if not drawer_button.exists(timeout=10):
        print("[ERROR] Could not find drawer menu button", file=sys.stderr)
        print(d.dump_hierarchy(), file=sys.stderr)
        exit(1)

    drawer_button.click()
    time.sleep(2)
    print("Sidebar menu opened", file=sys.stderr)

    # Step 2: Click "Add an account"
    print("Clicking 'Add an account'...", file=sys.stderr)
    wait_and_click_text("Add an account")

    # Step 3: Handle permissions screen - click "Do it later"
    print("Handling permissions screen...", file=sys.stderr)
    if d(text="Grant permissions").exists(timeout=10):
        print("Permissions screen detected, clicking 'Do it later'", file=sys.stderr)
        wait_and_click_text("Do it later")
    elif d(text="Do it later").exists(timeout=10):
        wait_and_click_text("Do it later")
    else:
        print("[INFO] No permissions screen detected, continuing...", file=sys.stderr)

    # Step 4: Wait for login screen to appear
    print("Waiting for login screen...", file=sys.stderr)
    if not d(text="Login").exists(timeout=15):
        print("[ERROR] Login screen did not appear", file=sys.stderr)
        print(d.dump_hierarchy(), file=sys.stderr)
        exit(1)

    # Step 5: Click "Use a third party SIP account"
    print("Clicking 'Use a third party SIP account'...", file=sys.stderr)
    if d(text="Use a third party SIP account").exists(timeout=10):
        wait_and_click_text("Use a third party SIP account")
    else:
        print(
            "[INFO] 'Use a third party SIP account' option not found, assuming already on login form",
            file=sys.stderr,
        )

    # Step 6: Handle terms and services screen
    print("Handling terms and services screen...", file=sys.stderr)
    if d(text="Accept").exists(timeout=10):
        wait_and_click_text("Accept")
    else:
        print(
            "[INFO] No terms and services screen detected, continuing...",
            file=sys.stderr,
        )
    wait_for_ui_stable(timeout=5, interval=1)
    if d(text="I understand").exists(timeout=10):
        wait_and_click_text("I understand")
    else:
        print(
            "[INFO] No 'I understand' prompt detected, continuing...", file=sys.stderr
        )

    wait_for_ui_stable(timeout=5, interval=1)

if d(resourceId="org.linphone:id/login", text="Login").exists(timeout=5):
    d.swipe_ext("down", scale=1)

# Step 7: Fill in Username
print(f"Filling username: {username}", file=sys.stderr)

# Use the exact resource ID from the XML
edit_username = d(resourceId="org.linphone:id/username")
if not edit_username.exists(timeout=10):
    print("[ERROR] Could not find Username field", file=sys.stderr)
    print(d.dump_hierarchy(), file=sys.stderr)
    exit(1)

edit_username.click()
time.sleep(1)
edit_username.clear_text()
time.sleep(0.5)

edit_username.set_text(username)
time.sleep(1)
print(f"Username set to: {username}", file=sys.stderr)

# Step 8: Fill in Password
print("Filling password", file=sys.stderr)

# Use the exact resource ID from the XML
edit_password = d(resourceId="org.linphone:id/password")
if not edit_password.exists(timeout=10):
    print("[ERROR] Could not find Password field", file=sys.stderr)
    print(d.dump_hierarchy(), file=sys.stderr)
    exit(1)

edit_password.click()
time.sleep(1)
edit_password.clear_text()
time.sleep(0.5)
edit_password.set_text(password)
time.sleep(1)
print("Password filled", file=sys.stderr)

# Step 9: Fill in Domain field (if it exists)
print(f"Filling domain: {domain}", file=sys.stderr)

# Look for Domain field by text label
if d(text="Domain*").exists(timeout=5) or d(textContains="Domain").exists(timeout=5):
    print("Found Domain field", file=sys.stderr)

    # Try to find by resource ID first
    edit_domain = d(resourceId="org.linphone:id/domain")
    if not edit_domain.exists():
        # Fallback: find EditText near "Domain" label
        domain_label = d(text="Domain*")
        if domain_label.exists():
            # Find the next EditText after the Domain label
            edit_domain = domain_label.sibling(className="android.widget.EditText")

    if edit_domain.exists():
        edit_domain.click()
        time.sleep(1)
        edit_domain.clear_text()
        time.sleep(0.5)
        edit_domain.set_text(domain)
        time.sleep(1)
        print(f"Domain set to: {domain}", file=sys.stderr)
    else:
        print("[WARNING] Could not find Domain EditText field", file=sys.stderr)
else:
    print("[INFO] No separate Domain field found", file=sys.stderr)

# Step 10: Set Transport (if needed and different from default)
if transport != "TLS":
    d.swipe_ext("up", scale=0.5)
    print(f"Setting transport to: {transport}", file=sys.stderr)

    if d(text="Transport").exists(timeout=5):
        transport_field = d(text="Transport")
        # Click on the dropdown (sibling or parent element)
        transport_dropdown = transport_field.sibling(className="android.widget.Spinner")
        if not transport_dropdown.exists():
            # Try finding by resource ID
            transport_dropdown = d(resourceId="org.linphone:id/transport")

        if transport_dropdown.exists():
            transport_dropdown.click()
            time.sleep(1)
            # Select the transport option
            if d(text=transport).exists(timeout=5):
                wait_and_click_text(transport)
            else:
                print(
                    f"[WARNING] Could not find transport option: {transport}",
                    file=sys.stderr,
                )
        else:
            print("[WARNING] Could not find Transport dropdown", file=sys.stderr)
else:
    print("[INFO] Using default transport (UDP)", file=sys.stderr)
d.swipe_ext("up", scale=0.5)

# Step 12: Click the Login button
print("Clicking Login button...", file=sys.stderr)

# Use the exact resource ID from the XML
login_button = d(resourceId="org.linphone:id/login", text="Login")
if not login_button.exists(timeout=10):
    print("[ERROR] Could not find Login button", file=sys.stderr)
    print(d.dump_hierarchy(), file=sys.stderr)
    exit(1)

wait_and_click_text("Login")
time.sleep(1)
if d(resourceId="org.linphone:id/login", text="Login").exists(timeout=5):
    wait_and_click_text("Login")
    time.sleep(1)

# Check for login result
print("Checking login result...", file=sys.stderr)
wait_for_ui_stable(timeout=10, interval=1)

# Check for error message
if d(text="Login").exists(timeout=5):
    print("[ERROR] Login failed", file=sys.stderr)
    print("FAILED")
    exit(1)

# Check for other error indicators
hierarchy = d.dump_hierarchy()
error_keywords = ["error", "Error", "failed", "Failed", "Wrong", "Invalid"]
for keyword in error_keywords:
    if keyword in hierarchy:
        print(f"[ERROR] Login failed: Found error keyword '{keyword}'", file=sys.stderr)
        print("FAILED")
        exit(1)

# If we got past errors and back to main screen, assume success
time.sleep(3)
if d(text="No call for the moment...").exists(timeout=10) or d(text="Calls").exists(
    timeout=10
):
    print("[SUCCESS] Login successful - returned to main screen", file=sys.stderr)
    print("SUCCESS")
    exit(0)
else:
    print(
        "[WARNING] Login status unclear - no error but not on main screen",
        file=sys.stderr,
    )
    print(d.dump_hierarchy(), file=sys.stderr)
    print("UNKNOWN")
    exit(2)
