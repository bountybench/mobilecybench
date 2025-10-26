import json
import os
import secrets
import string
import uuid
from typing import Any, Dict, List

import bcrypt
import yaml


def get_uuid(length: int = 36) -> str:
    """Generate a UUID string with an optional length limit (max 36)."""
    length = min(length, 36)
    uuid_str = str(uuid.uuid4())
    return uuid_str[:length]


def hash_password(password: str, cost: int = None, encoding: str = "utf-8") -> str:
    """
    Generate a bcrypt hash from a password.

    Args:
        password: The plain text password to hash
        cost: The bcrypt cost factor (defaults to bcrypt's default if None)
        encoding: The encoding to use for password (defaults to "utf-8")

    Returns:
        The bcrypt hash as a string
    """
    if cost is None:
        return bcrypt.hashpw(password.encode(encoding), bcrypt.gensalt()).decode(
            encoding
        )
    else:
        return bcrypt.hashpw(password.encode(encoding), bcrypt.gensalt(cost)).decode(
            encoding
        )


def generate_secrets(
    template: Dict[str, Any], include_password_hash: bool = True
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


def generate_random_flag(prefix: str = "", length: int = 16) -> str:
    """
    Generate a random flag value.

    Args:
        prefix: Optional prefix for the flag (e.g., "app_files", "server_password")
                A hyphen will be automatically added between prefix and random part
        length: Length of the random part (default 16 characters)

    Returns:
        A randomly generated flag string in format: prefix-randompart
    """
    random_part = "".join(
        secrets.choice(string.ascii_lowercase + string.digits) for _ in range(length)
    )
    return f"{prefix}-{random_part}"


def generate_and_save_flags(
    output_path: str, container_names: list = None
) -> Dict[str, str]:
    """
    Generate random flags and save them to a JSON file.

    Args:
        output_path: Directory path where flags.json will be saved
        container_names: Optional list of container names to generate per-container flags.
                        If provided, generates flags like "container-name-random"

    Returns:
        Dictionary containing the generated flags
    """
    flags = {
        "APP_FILES_FLAG_CONTENT": generate_random_flag("app_files"),
    }

    # Generate per-container flags if container names are provided
    if container_names:
        flags["CONTAINER_FLAGS"] = {}
        for container_name in container_names:
            # Generate flag with format: container-name-random
            flags["CONTAINER_FLAGS"][container_name] = generate_random_flag(
                container_name
            )
    else:
        # Fallback to single global flag if no container names provided
        flags["SERVER_PASSWORD_FLAG_CONTENT"] = generate_random_flag("server_password")

    filename = os.path.join(output_path, "flags.json")
    os.makedirs(output_path, exist_ok=True)
    with open(filename, "w") as json_file:
        json.dump(flags, json_file, indent=4)
    print(f"Random flags generated and saved to {filename}")
    return flags


def load_flags(flags_file: str) -> Dict[str, str]:
    """
    Load flags from a JSON file.

    Args:
        flags_file: Path to the flags.json file

    Returns:
        Dictionary containing the flags
    """
    if not os.path.exists(flags_file):
        raise FileNotFoundError(f"Flags file not found: {flags_file}")

    with open(flags_file, "r") as f:
        flags = json.load(f)

    return flags


def extract_container_names_from_compose(docker_compose_path: str) -> List[str]:
    """
    Extract container names from a docker-compose.yml file.

    Args:
        docker_compose_path: Path to the docker-compose.yml file

    Returns:
        List of container names defined in the docker-compose file
    """
    if not os.path.exists(docker_compose_path):
        return []

    try:
        with open(docker_compose_path, "r") as f:
            compose_data = yaml.safe_load(f)

        container_names = []
        services = compose_data.get("services", {})

        for _, service_config in services.items():
            if isinstance(service_config, dict) and "container_name" in service_config:
                container_names.append(service_config["container_name"])

        return container_names
    except Exception as e:
        print(f"Error extracting container names from {docker_compose_path}: {e}")
        return []
