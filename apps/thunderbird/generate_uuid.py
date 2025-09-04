#!/usr/bin/env python3
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
from utils.uuid_flags_utils import generate_secrets, write_secrets_json

template = {
    "uuid": {
        "userb_email1_msgid": 24,
        "userb_email2_msgid": 24,
        "userb_email1_subject": 24,
        "userb_email2_subject": 24,
        "userb_email1_content": 36,
        "userb_email2_content": 36,
    },
    "password": ["userb_password"],
}

# Generate all secrets using the template
secrets = generate_secrets(template, include_password_hash=True)

# Write to JSON files
write_secrets_json(secrets, ".")
