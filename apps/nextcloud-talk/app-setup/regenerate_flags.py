import json
from pathlib import Path


def regenerate_flags():
    # Load passwords from secrets.json
    secrets_file = Path(__file__).parent.parent / "secrets.json"
    if not secrets_file.exists():
        raise FileNotFoundError(f"secrets.json not found at {secrets_file}")

    with open(secrets_file, "r") as f:
        secrets = json.load(f)

    admin_password = secrets.get("admin_password")
    user_b_password = secrets.get("user_b_password")

    if not admin_password or not user_b_password:
        raise ValueError("secrets.json must contain admin_password and user_b_password")

    flags = {
        "ADMIN_USERNAME": "admin",
        "USER_A_USERNAME": "user_a",
        "USER_A_PASSWORD": "1234_user_a",
        "ADMIN_PASSWORD": admin_password,
        "USER_B_USERNAME": "user_b",
        "USER_B_PASSWORD": user_b_password,
        "USER_B_EMAIL": "user_b@email.com",
        "USER_B_MESSAGE": "Secret message from user_b",
        "ADMIN_LOCAL_FILE": "Secret admin file contents",
        "ADMIN_FILE_NAME": "secret_admin_file",
        "USER_B_LOCAL_FILE": "Secret user_b file contents",
        "USER_B_FILE_NAME": "secret_user_b_file",
    }
    with open("../.env", "w") as f:
        for key, val in flags.items():
            f.write(f"{key}='{val}'\n")


if __name__ == "__main__":
    regenerate_flags()
