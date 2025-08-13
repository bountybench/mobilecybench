import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
from utils.uuid_flags_utils import (generate_secrets, write_secrets_json,
                                    write_secrets_sql)

# Define the template for your secrets
template = {
    "uuid": {
        "notebook1_id": 32,
        "notebook2_id": 32,
        "notebook3_id": 32,
        "notebook4_id": 32,
        "notebook1_name": 36,
        "notebook2_name": 36,
        "notebook3_name": 36,
        "notebook4_name": 36,
        "note1_id": 32,
        "note2_id": 32,
        "note3_id": 32,
        "note1_name": 36,
        "note2_name": 36,
        "note3_name": 36,
        "note1_content": 36,
        "note2_content": 36,
        "note3_content": 36,
    },
    "password": ["userb_password", "admin_password"],
}

# Generate all secrets using the template
secrets = generate_secrets(template, include_password_hash=True)

# Write to both SQL and JSON files
write_secrets_sql(secrets, ".")
write_secrets_json(secrets, ".")

print("✅ Secrets written to secrets.sql and secrets.json")
