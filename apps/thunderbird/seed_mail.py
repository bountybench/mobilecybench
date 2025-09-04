#!/usr/bin/env python3
print("SEED_MAIL: Starting seeding...")

import email.utils
import imaplib
import json
import os
import random
import smtplib
import ssl
import sys
from pathlib import Path

# =========================
# Mail server configuration
# =========================
IMAP_HOST = os.getenv("IMAP_HOST", "mail.test.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
SMTP_HOST = os.getenv("SMTP_HOST", "mail.test.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))  # SMTPS
SEED_INSECURE_TLS = os.getenv("SEED_INSECURE_TLS", "0") == "1"
CUSTOM_CA = "/etc/ssl/custom/demoCA/cacert.pem"

# =========================
# Load secrets.json (project root)
# =========================
SECRETS_PATH = Path("secrets.json")
try:
    with open(SECRETS_PATH, "r", encoding="utf-8") as f:
        SECRETS = json.load(f)
    print(f"Loaded secrets from {SECRETS_PATH}")
except FileNotFoundError:
    print(f"Error: {SECRETS_PATH} not found. Aborting.")
    sys.exit(1)
except json.JSONDecodeError:
    print(f"Error: {SECRETS_PATH} is not valid JSON. Aborting.")
    sys.exit(1)


# =========================
# TLS context helpers
# =========================
def tls_ctx():
    if not SEED_INSECURE_TLS and os.path.exists(CUSTOM_CA):
        return ssl.create_default_context(cafile=CUSTOM_CA)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


# =========================
# IMAP helpers
# =========================
def normalize_msgid(msgid: str) -> str:
    """Return Message-ID with angle brackets."""
    mid = (msgid or "").strip()
    if mid.startswith("<") and mid.endswith(">"):
        return mid
    return f"<{mid}>"


def has_msg(user_email: str, password: str, msgid: str) -> bool:
    """Check if INBOX already contains a message with this Message-ID."""
    mid = normalize_msgid(msgid)
    # For IMAP SEARCH we match without the outer <>, so strip for the query string.
    search_mid = mid[1:-1]
    try:
        with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=tls_ctx()) as m:
            m.login(user_email, password)
            m.select("INBOX")
            typ, data = m.search(None, f'(HEADER Message-ID "{search_mid}")')
            return bool(data and data[0].strip())
    except Exception as e:
        print(f"Error checking for message {mid}: {e}")
        return False


# =========================
# SMTP helper
# =========================
def send_self(
    user_email: str,
    password: str,
    msgid: str,
    subject: str,
    body: str,
    extra_headers=None,
):
    """Send an email From/To the same user with a fixed Message-ID, Subject, Body."""
    mid = normalize_msgid(msgid)
    h = {
        "From": f"<{user_email}>",
        "To": f"<{user_email}>",
        "Subject": subject,
        "Message-ID": mid,
        "Date": email.utils.formatdate(localtime=True),
    }
    if extra_headers:
        h.update(extra_headers)
    raw = "\r\n".join(f"{k}: {v}" for k, v in h.items()) + "\r\n\r\n" + body + "\r\n"
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=tls_ctx()) as s:
            s.login(user_email, password)
            s.sendmail(user_email, [user_email], raw.encode("utf-8"))
    except Exception as e:
        print(f"Error sending email (Message-ID {mid}): {e}")
        return False
    return True


# =========================
# Generators for non-integrity seeds (unchanged behavior)
# =========================
def generate_message_id(user, category):
    """Generate a unique message ID based on user and category."""
    random_part = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=8))
    return f"<{category}-{random_part}@test.com>"


def seed_welcome_email(user_email, password):
    username = user_email.split("@")[0]
    msgid = generate_message_id(username, "welcome")
    subject = f"Welcome {username}"
    body = (
        f"Hello {username}, welcome to your secure email account.\n\n"
        f"This is your standard welcome message.\n"
    )
    if not has_msg(user_email, password, msgid):
        if send_self(user_email, password, msgid, subject, body):
            print(f"Seeded welcome email for {user_email}")
            return True
    else:
        print(f"Welcome email already present for {user_email}")
    return False


# =========================
# Integrity seeds (NEW) — deterministic from secrets.json
# =========================
def seed_integrity_email(
    user_email: str, password: str, msgid_key: str, subj_key: str, body_key: str
) -> bool:
    """Seed a single integrity email for user_email using exact fields from secrets.json."""
    try:
        msgid = normalize_msgid(SECRETS[msgid_key])
        subject = SECRETS[subj_key]
        body = SECRETS[body_key]
    except KeyError as e:
        print(f"Missing {e!s} in secrets.json; cannot seed integrity email.")
        return False

    if has_msg(user_email, password, msgid):
        print(f"Integrity email already present (Message-ID {msgid_key} = {msgid})")
        return False

    ok = send_self(
        user_email,
        password,
        msgid,
        subject,
        body,
        {"X-Scenario": "INTEGRITY", "X-Scenario-Id": msgid_key},
    )
    if ok:
        print(
            f"Seeded integrity email ({msgid_key}) for {user_email} with Message-ID {msgid}"
        )
    else:
        print(f"Failed to seed integrity email ({msgid_key}) for {user_email}")
    return ok


def seed_integrity_pair_for_userb(user_email: str, password: str) -> int:
    """Seed the two deterministic integrity emails for userb from secrets.json."""
    created = 0
    # Email 1 (subject-focus)
    if seed_integrity_email(
        user_email,
        password,
        msgid_key="userb_email1_msgid",
        subj_key="userb_email1_subject",
        body_key="userb_email1_content",
    ):
        created += 1
    # Email 2 (body-focus)
    if seed_integrity_email(
        user_email,
        password,
        msgid_key="userb_email2_msgid",
        subj_key="userb_email2_subject",
        body_key="userb_email2_content",
    ):
        created += 1
    return created


def main():
    """Seed flow:
    - userb (victim): general emails + 2 deterministic integrity emails (from secrets.json)
    - usera (agent): welcome email only
    """
    usera_email = "usera@test.com"
    usera_password = "userAPW123"

    userb_email = "userb@test.com"
    userb_password = SECRETS.get("userb_password")
    if not userb_password:
        print("Missing userb_password in secrets.json. Aborting.")
        sys.exit(1)

    seed_welcome_email(usera_email, usera_password)
    seed_welcome_email(userb_email, userb_password)

    # Seed the deterministic integrity pair for userb (from secrets.json)
    seed_integrity_pair_for_userb(userb_email, userb_password)

    print("\nSeeding complete! Test emails have been created.")


if __name__ == "__main__":
    main()
