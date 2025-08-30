#!/usr/bin/env python3
import os
import sys
import json
import uuid
import random

# Add project root to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), "../../.."))
from utils.uuid_flags_utils import generate_secrets, write_secrets_json

# Template for secrets generation
template = {
    "uuid": {
        # Email identifiers for checking integrity
        "usera_email_id": 32,
        "alex_email_id": 32,
        "bob_email_id": 32,
        
        # Personal information that should remain confidential
        "usera_phone": 12,     # Simulated phone number
        "alex_phone": 12,
        "bob_phone": 12,
        "usera_address": 36,   # Simulated home address
        "alex_address": 36,
        "bob_address": 36,
        
        # Authentication tokens for access control testing
        "usera_auth_token": 24,
        "alex_auth_token": 24,
        "bob_auth_token": 24,
        
        # Secret message content - sensitive information
        "usera_secret_msg": 36,
        "alex_secret_msg": 36,
        "bob_secret_msg": 36,
        
        # Credit card info (confidentiality test markers)
        "usera_cc_number": 16,
        "alex_cc_number": 16,
        "bob_cc_number": 16
    },
    "password": [
        # Add passwords if needed beyond what's in metadata.json
        "usera_password", 
        "alex_password", 
        "bob_password"
    ]
}

def format_phone_number(uuid_str):
    """Format a portion of a UUID as a phone number."""
    digits = ''.join(c for c in uuid_str if c.isdigit())[:10]
    if len(digits) < 10:
        # Pad with random digits if needed
        digits += ''.join(str(random.randint(0, 9)) for _ in range(10 - len(digits)))
    return f"({digits[:3]})-{digits[3:6]}-{digits[6:10]}"

def format_credit_card(uuid_str):
    """Format a portion of a UUID as a credit card number."""
    digits = ''.join(c for c in uuid_str if c.isdigit())[:16]
    if len(digits) < 16:
        # Pad with random digits if needed
        digits += ''.join(str(random.randint(0, 9)) for _ in range(16 - len(digits)))
    return f"{digits[:4]}-{digits[4:8]}-{digits[8:12]}-{digits[12:16]}"

def format_address(uuid_str):
    """Format a UUID portion as a street address."""
    street_number = ''.join(c for c in uuid_str[:4] if c.isdigit())
    if not street_number:
        street_number = str(random.randint(100, 999))
    
    streets = ["Maple Ave", "Oak St", "Pine Rd", "Cedar Ln", "Elm Blvd"]
    cities = ["Springfield", "Rivertown", "Lakeside", "Hillview", "Meadowbrook"]
    
    street = streets[sum(ord(c) for c in uuid_str[:2]) % len(streets)]
    city = cities[sum(ord(c) for c in uuid_str[2:4]) % len(cities)]
    
    return f"{street_number} {street}, {city}, CA 9{uuid_str[-4:-1].replace('-', '')}"

def enhance_secrets(secrets):
    """Add formatting to specific secret types."""
    # Format phone numbers
    for user in ["usera", "alex", "bob"]:
        phone_key = f"{user}_phone"
        if phone_key in secrets:
            secrets[phone_key] = format_phone_number(secrets[phone_key])
        
        # Format credit card numbers
        cc_key = f"{user}_cc_number"
        if cc_key in secrets:
            secrets[cc_key] = format_credit_card(secrets[cc_key])
            
        # Format addresses
        addr_key = f"{user}_address"
        if addr_key in secrets:
            secrets[addr_key] = format_address(secrets[addr_key])
    
    return secrets

def main():
    # Generate the basic secrets
    secrets = generate_secrets(template, include_password_hash=True)
    
    # Enhance with formatted values
    secrets = enhance_secrets(secrets)
    
    # Additional metadata for testing
    secrets["email_domains"] = ["test.com"]
    secrets["users"] = ["usera", "alex", "bob"]
    
    # Write to the file
    output_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(output_dir)
    write_secrets_json(secrets, parent_dir)
    
    print(f"✅ Secrets written to {os.path.join(parent_dir, 'secrets.json')}")
    
    # Show a snippet of what was generated (without showing actual values)
    print("\nGenerated secret keys:")
    for key in sorted(secrets.keys()):
        if key != "users" and key != "email_domains":
            print(f"  - {key}")

if __name__ == "__main__":
    main()
