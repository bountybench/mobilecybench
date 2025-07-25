import uuid
import json
import bcrypt
import argparse
import os
from typing import Dict, Any

def get_uuid(length: int = 36) -> str:
    """Generate a UUID string with an optional length limit (max 36)."""
    length = min(length, 36)
    uuid_str = str(uuid.uuid4())
    return uuid_str[:length]


def hash_password(password: str) -> str:
    """Generate a bcrypt hash from a password."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def generate_secrets(
    template: Dict[str, Any],
    include_password_hash: bool = True
) -> Dict[str, Any]:
    """
    Generate secrets based on a template.

    Template format example:
    {
        "uuid": {
            "admin_secret": 36,
            "userB_secret": 32
        },
        "password": ["admin_password", "userB_password"]
    }
    """
    secrets = {}

    # Generate UUIDs with specified lengths
    for key, length in template.get("uuid", {}).items():
        secrets[key] = get_uuid(length)

    # Generate passwords & hashes
    for key in template.get("password", []):
        plain_password = get_uuid()  # random password as UUID
        secrets[key] = plain_password
        if include_password_hash:
            secrets[f"{key}_hash"] = hash_password(plain_password)

    return secrets


def write_secrets_sql(secrets: Dict[str, Any], output_path: str):
    """Write secrets into a .sql file as PostgreSQL variables."""
    filename = os.path.join(output_path, "secrets.sql")
    with open(filename, "w") as sql_file:
        for key, value in secrets.items():
            sql_file.write(f"\\set {key} '''{value}'''\n")
    print(f"✅ SQL secrets written to {filename}")


def write_secrets_json(secrets: Dict[str, Any], output_path: str):
    """Write secrets into a JSON file."""
    filename = os.path.join(output_path, "secrets.json")
    with open(filename, "w") as json_file:
        json.dump(secrets, json_file, indent=4)
    print(f"✅ JSON secrets written to {filename}")