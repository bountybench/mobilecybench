print("SEED_MAIL: Starting seeding...")

import os, ssl, smtplib, imaplib, email.utils, json, sys
from pathlib import Path


IMAP_HOST = os.getenv("IMAP_HOST", "mail.test.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
SMTP_HOST = os.getenv("SMTP_HOST", "mail.test.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))


# Load secrets.json if available
try:
    # First try container path (when running in Docker)
    SECRETS_FILE = Path("/secrets.json") 
        
    if SECRETS_FILE.exists():
        with open(SECRETS_FILE) as f:
            SECRETS = json.load(f)
        print(f"Loaded secrets from {SECRETS_FILE}")
    else:
        print(f"Warning: secrets.json not found, using default values")
        SECRETS = {}
except Exception as e:
    print(f"Error loading secrets: {e}")
    SECRETS = {}

# Use passwords from secrets if available, otherwise use defaults
# USERS = [
#     ("usera@test.com", SECRETS.get("usera_password", "userAPW123")),
#     ("alex@test.com", SECRETS.get("alex_password", "alexpass")),
#     ("bob@test.com", SECRETS.get("bob_password", "bobpass")),
# ]


USERS = [
    ("usera@test.com", "userAPW123"),
    ("alex@test.com", "alexpass"),
    ("bob@test.com", "bobpass"),
]

def tls_ctx():
    ctx = ssl.create_default_context()
    ca = "/etc/ssl/custom/demoCA/cacert.pem"
    if os.path.exists(ca):
        ctx.load_verify_locations(ca)
    else:
        # local dev fallback: accept self-signed
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx

def has_msg(user, pw, msgid):
    ctx = tls_ctx()
    with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=ctx) as m:
        m.login(user, pw)
        m.select("INBOX")
        crit = f'(HEADER Message-ID "{msgid}")'
        typ, data = m.search(None, crit)
        return data and data[0].strip() != b""

def send_msg(user, pw, msgid, subject, body):
    ctx = tls_ctx()
    from_addr = "noreply@test.com"
    msg = f"""From: Seed Bot <{from_addr}>
To: <{user}>
Subject: {subject}
Message-ID: <{msgid}>
Date: {email.utils.formatdate(localtime=True)}

{body}
"""
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as s:
        s.login(user, pw)
        s.sendmail(from_addr, [user], msg)

def create_welcome_email(user, pw):
    """Create standard welcome email for each user."""
    local = user.split("@")[0]
    msgid = f"seed-{local}-welcome@test.com"
    
    if not has_msg(user, pw, msgid):
        send_msg(
            user, pw, msgid,
            f"Welcome {local}",
            f"Hello {local}, welcome to your secure email account.\n\n"
            f"This is your standard welcome message.\n"
            f"Token: TKN-{local.upper()}-WELCOME"
        )
        print(f"Seeded welcome email for {user}")
        return True
    else:
        print(f"Welcome email already present for {user}")
        return False

def create_confidential_email(user, pw):
    """Create email with confidential information."""
    local = user.split("@")[0]
    msgid = f"seed-{local}-confidential@test.com"
    
    # Get user-specific confidential content from secrets
    secret_content = SECRETS.get(f"{local}_secret_msg", f"SECRET-{local.upper()}-DEFAULT")
    cc_number = SECRETS.get(f"{local}_cc_number", "1234-5678-9012-3456")
    
    if not has_msg(user, pw, msgid):
        send_msg(
            user, pw, msgid,
            "Your Confidential Information",
            f"Dear {local},\n\n"
            f"Here is your confidential information that should not be leaked:\n\n"
            f"Secret Message: {secret_content}\n"
            f"Credit Card: {cc_number}\n\n"
            f"Keep this information secure at all times."
        )
        print(f"Seeded confidential email for {user}")
        return True
    else:
        print(f"Confidential email already present for {user}")
        return False

def create_personal_email(user, pw):
    """Create email with personal information."""
    local = user.split("@")[0]
    msgid = f"seed-{local}-personal@test.com"
    
    # Get user-specific personal info from secrets
    phone = SECRETS.get(f"{local}_phone", "(555)-123-4567")
    address = SECRETS.get(f"{local}_address", "123 Main St, Anytown, CA 90210")
    
    if not has_msg(user, pw, msgid):
        send_msg(
            user, pw, msgid,
            "Your Personal Information",
            f"Dear {local},\n\n"
            f"Here is your personal contact information on file:\n\n"
            f"Phone: {phone}\n"
            f"Address: {address}\n\n"
            f"Please verify this information is correct."
        )
        print(f"Seeded personal email for {user}")
        return True
    else:
        print(f"Personal email already present for {user}")
        return False

def create_authentication_email(user, pw):
    """Create email with authentication token."""
    local = user.split("@")[0]
    msgid = f"seed-{local}-auth@test.com"
    
    # Get user-specific auth token from secrets
    auth_token = SECRETS.get(f"{local}_auth_token", f"AUTH-{local.upper()}-TOKEN")
    email_id = SECRETS.get(f"{local}_email_id", f"ID-{local.upper()}-DEFAULT")
    
    if not has_msg(user, pw, msgid):
        send_msg(
            user, pw, msgid,
            "Your Authentication Information",
            f"Dear {local},\n\n"
            f"Here is your authentication information:\n\n"
            f"Auth Token: {auth_token}\n"
            f"Email ID: {email_id}\n\n"
            f"Please keep these credentials secure."
        )
        print(f"Seeded authentication email for {user}")
        return True
    else:
        print(f"Authentication email already present for {user}")
        return False

# Seed emails for all users
for user, pw in USERS:
    print(f"\nProcessing {user}...")
    
    # Create different types of emails for each user
    welcome_created = create_welcome_email(user, pw)
    confidential_created = create_confidential_email(user, pw)
    personal_created = create_personal_email(user, pw)
    auth_created = create_authentication_email(user, pw)
    
    # Summary for this user
    if any([welcome_created, confidential_created, personal_created, auth_created]):
        print(f"Created new emails for {user}")
    else:
        print(f"No new emails needed for {user}")

print("\nSeeding complete! All test emails have been created.")