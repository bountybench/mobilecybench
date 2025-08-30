#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

# Note: requires uiautomator2 package - install with: pip install uiautomator2
import uiautomator2 as u2

# Parse command line arguments
parser = argparse.ArgumentParser(description="Thunderbird email account setup")
parser.add_argument("--username", help="Email address")
parser.add_argument("--password", help="Email password")
parser.add_argument("--host", help="Email server hostname")
parser.add_argument("--imap_port", help="IMAP port")
parser.add_argument("--smtp_port", help="SMTP port")
args = parser.parse_args()

# Load from metadata if args not provided
try:
    metadata_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "metadata.json")
    with open(metadata_path) as f:
        metadata = json.load(f)
    
    EMAIL = args.username or metadata.get("username", "usera@test.com")
    PASS = args.password or metadata.get("password", "userAPW123")
    HOST = args.host or "10.0.2.2"  # Default to emulator localhost
    IMAP_PORT = args.imap_port or "993"  # SSL/TLS IMAP
    SMTP_PORT = args.smtp_port or "465"  # SSL/TLS SMTP
except Exception as e:
    print(f"[WARNING] Error loading metadata: {e}", file=sys.stderr)
    EMAIL = args.username or "usera@test.com"
    PASS = args.password or "userAPW123"
    HOST = args.host or "10.0.2.2"
    IMAP_PORT = args.imap_port or "993"
    SMTP_PORT = args.smtp_port or "465"

PKG = "net.thunderbird.android"

# Connect to the device
print(f"[INFO] Connecting to device", file=sys.stderr)
d = u2.connect()
d.app_start(PKG)
d.wait_timeout = 15  # Set global timeout to 15 seconds

def wait_for_ui_stable(timeout=10, interval=0.5):
    """
    Wait until the UI hierarchy stops changing.
    """
    prev_hierarchy = None
    start = time.time()

    while time.time() - start < timeout:
        current_hierarchy = d.dump_hierarchy(compressed=True)
        if current_hierarchy == prev_hierarchy:
            return True
        prev_hierarchy = current_hierarchy
        time.sleep(interval)
    return False

def wait_and_click_text(text, timeout=45):
    """Wait for text to appear and click it"""
    print(f"[INFO] Waiting for text: '{text}'", file=sys.stderr)
    if d(text=text).wait(timeout=timeout):
        d(text=text).click_exists(timeout=3)
        print(f"[INFO] Clicked: '{text}'", file=sys.stderr)
    else:
        print(f"[ERROR] Could not find text: '{text}' within {timeout}s", file=sys.stderr)
        print(d.dump_hierarchy(), file=sys.stderr)
        exit(1)
    wait_for_ui_stable(timeout=5)

def wait_and_click_desc(desc, timeout=45):
    """Wait for element with description to appear and click it"""
    print(f"[INFO] Waiting for description: '{desc}'", file=sys.stderr)
    if d(description=desc).wait(timeout=timeout):
        d(description=desc).click_exists(timeout=3)
        print(f"[INFO] Clicked description: '{desc}'", file=sys.stderr)
    else:
        print(f"[ERROR] Could not find description: '{desc}' within {timeout}s", file=sys.stderr)
        print(d.dump_hierarchy(), file=sys.stderr)
        exit(1)
    wait_for_ui_stable(timeout=5)

def tap_if_exists(text=None, desc=None, id=None, timeout=5):
    """Try to tap an element if it exists"""
    if text and d(text=text).exists(timeout=timeout):
        d(text=text).click()
        print(f"[INFO] Tapped text: '{text}'", file=sys.stderr)
        wait_for_ui_stable(timeout=5)
        return True
    elif desc and d(description=desc).exists(timeout=timeout):
        d(description=desc).click()
        print(f"[INFO] Tapped description: '{desc}'", file=sys.stderr)
        wait_for_ui_stable(timeout=5)
        return True
    elif id and d(resourceId=id).exists(timeout=timeout):
        d(resourceId=id).click()
        print(f"[INFO] Tapped resourceId: '{id}'", file=sys.stderr)
        wait_for_ui_stable(timeout=5)
        return True
    return False

def type_text(text_to_type, field_text=None, field_id=None, field_desc=None, field_class=None, field_index=0):
    """Type text into a field identified by various properties"""
    target = None
    
    if field_text:
        if d(text=field_text).exists:
            # Try to find editable sibling
            target = d(text=field_text).sibling(className="android.widget.EditText")
            if not target.exists:
                # Try to find next editable field
                target = d(className="android.widget.EditText")
    elif field_id and d(resourceId=field_id).exists:
        target = d(resourceId=field_id)
    elif field_desc and d(description=field_desc).exists:
        target = d(description=field_desc)
    elif field_class:
        if field_index is not None:
            target = d(className=field_class, instance=field_index)
        else:
            target = d(className=field_class)
    
    if target and target.exists:
        target.click()
        time.sleep(1)
        target.set_text("")  # Clear text
        time.sleep(1)
        d.send_keys(text_to_type)
        print(f"[INFO] Typed: '{text_to_type}'", file=sys.stderr)
        return True
    
    print(f"[WARNING] Could not find text field to type: '{text_to_type}'", file=sys.stderr)
    return False

def handle_security_warning():
    """Handle security warnings related to self-signed certificates"""
    # Try different text variations that could appear in security warning dialogs
    security_buttons = [
        "Accept risk and continue", "Advanced"
    ]
    
    for button in security_buttons:
        if tap_if_exists(text=button):
            print(f"[INFO] Handled security warning with: '{button}'", file=sys.stderr)
            wait_for_ui_stable(timeout=5)
            return True
    return False

def setup_incoming_server():
    """
    Handle the incoming server settings page. This function tries multiple methods
    to identify and fill in the server hostname and password fields.
    """
    print("[INFO] Setting up incoming server", file=sys.stderr)
    wait_for_ui_stable(timeout=5)   
    
    # Try by field index first after handling potential dropdowns
    edit_texts = d(className="android.widget.EditText")
    print(f"[INFO] Found {edit_texts.count} EditText fields", file=sys.stderr)
    
    if edit_texts.count >= 1:
        # The server field should now be accessible at index 0
        server_field = d(className="android.widget.EditText", instance=1)
        if server_field.exists:
            server_field.click()
            time.sleep(1)
            server_field.set_text("")
            time.sleep(1)
            d.send_keys(HOST)
            print(f"[INFO] Typed server hostname using index method: '{HOST}'", file=sys.stderr) 
       
        password_field = d(className="android.widget.EditText", instance=6)
        if password_field.exists:   
            password_field.click()
            time.sleep(1)
            password_field.set_text("")
            time.sleep(1)
            d.send_keys(PASS)
            print(f"[INFO] Typed password using index method", file=sys.stderr) 

def setup_outgoing_server():
    """
    Handle the outgoing server settings page. This function uses EditText indexing
    to identify and fill in the server hostname and other fields. 
    """
    print("[INFO] Setting up outgoing server", file=sys.stderr)
    wait_for_ui_stable(timeout=5)
    
    # Try by field index first
    edit_texts = d(className="android.widget.EditText")
    print(f"[INFO] Found {edit_texts.count} EditText fields for outgoing server", file=sys.stderr)
    
    if edit_texts.count >= 1: 
        server_field = d(className="android.widget.EditText", instance=0)
        if server_field.exists:
            server_field.click()
            time.sleep(1)
            server_field.set_text("")
            time.sleep(1)
            d.send_keys(HOST)
            print(f"[INFO] Typed outgoing server hostname using index method: '{HOST}'", file=sys.stderr)
         
        # Password field - index might need adjustment
        password_field = d(className="android.widget.EditText", instance=5)
        if password_field.exists:
            password_field.click()
            time.sleep(1)
            password_field.set_text("")
            time.sleep(1)
            d.send_keys(PASS)
            print(f"[INFO] Typed password using index method", file=sys.stderr) 

def setup_display_options():
    """
    Handle the display options page. This function uses EditText indexing
    to identify and fill in the account name and your name* fields.
    """
    print("[INFO] Setting up display options", file=sys.stderr) 
    account_name_field = d(className="android.widget.EditText", instance=0)
    if account_name_field.exists:
            account_name_field.click()
            time.sleep(1)
            account_name_field.set_text("")
            time.sleep(1)
            d.send_keys(EMAIL)
            print(f"[INFO] Typed account name using index method: '{EMAIL}'", file=sys.stderr) 
    your_name_field = d(className="android.widget.EditText", instance=1)
    if your_name_field.exists:
            your_name_field.click()
            time.sleep(1)
            your_name_field.set_text("")
            time.sleep(1)
            d.send_keys(EMAIL)
            print(f"[INFO] Typed your name* using index method: '{EMAIL}'", file=sys.stderr)
    signature_field = d(className="android.widget.EditText", instance=2)
    if signature_field.exists:
            signature_field.click()
            time.sleep(1)
            signature_field.set_text("")
            time.sleep(1)
            d.send_keys(EMAIL)
            print(f"[INFO] Typed email signature using index method: '{EMAIL}'", file=sys.stderr)
    
    
def main():
    print("[INFO] Starting Thunderbird account setup", file=sys.stderr)
    wait_for_ui_stable(timeout=10)
    
    # Click "Get started" button     
    tap_if_exists(text="Get started") 
      
    # d(className="android.widget.Button", textContains="start").click()
    
    # Wait longer after clicking the button
    wait_for_ui_stable(timeout=10)
        
    # Add email account
    tap_if_exists(text="Add an email account now")
    wait_for_ui_stable()
    
    # Enter email address
    type_text(EMAIL, field_text="Email address")
    time.sleep(2)
    
    # Click Next
    tap_if_exists(text="Next") 
    wait_for_ui_stable(timeout=10)
    
    # Handle "Configuration not found" by clicking Next again
    time.sleep(15)  # Wait a bit to see if config not found appears
    tap_if_exists(text="Next", timeout=3)  
    wait_for_ui_stable(timeout=5)
    
    # Setup incoming server settings using the dedicated function
    setup_incoming_server()
    
    # Click Next
    tap_if_exists(text="Next")  
    wait_for_ui_stable()
    
    # Handle security warnings
    handle_security_warning()
    wait_for_ui_stable()
    handle_security_warning() 
    
    # Setup outgoing server settings using the dedicated function
    setup_outgoing_server()
    
    # Click Next
    tap_if_exists(text="Next") 
    wait_for_ui_stable()
    
    # Handle security warnings
    handle_security_warning()
    wait_for_ui_stable()
    handle_security_warning()
    wait_for_ui_stable()
    
    # Next for account options
    tap_if_exists(text="Next") 
    wait_for_ui_stable()
     
    # Setup display options using the dedicated function
    setup_display_options()
    
    # Final next
    tap_if_exists(text="Next") 
    wait_for_ui_stable()
    tap_if_exists(text="Next") 
    wait_for_ui_stable()
    
    # Skip if presented  
    wait_for_ui_stable(15)
    tap_if_exists(text="Skip")  
    
    print("[INFO] Thunderbird account setup completed successfully", file=sys.stderr)
    return 0

if __name__ == "__main__":
    try:
        exit(main())
    except Exception as e:
        print(f"[ERROR] Unhandled exception: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        exit(1)