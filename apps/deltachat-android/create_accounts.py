import json
import logging
import os
import sys

logger = logging.getLogger("mobilecybench.deltachat.create_accounts")
logger.setLevel("INFO")
_handler = logging.StreamHandler(stream=sys.stderr)
_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logger.handlers[:] = [_handler]
logger.propagate = False


def create_accounts_json():
    script_dir = os.path.dirname(os.path.abspath(__file__))

    accounts = {
        "users": [
            {
                "email": "user1@deltachat.test",
                "password": "password123",
                "name": "Test User 1",
            },
            {
                "email": "user2@deltachat.test",
                "password": "password123",
                "name": "Test User 2",
            },
            {
                "email": "user3@deltachat.test",
                "password": "password123",
                "name": "Test User 3",
            },
        ],
        "smtp_server": "10.0.2.2",
        "smtp_port": 1025,
        "imap_server": "10.0.2.2",
        "imap_port": 1143,
    }

    accounts_file = os.path.join(script_dir, "accounts.json")
    with open(accounts_file, "w") as f:
        json.dump(accounts, f, indent=2)

    logger.info("Created accounts.json with %d test users", len(accounts["users"]))
    return accounts


def create_secrets_json():
    script_dir = os.path.dirname(os.path.abspath(__file__))

    accounts_file = os.path.join(script_dir, "accounts.json")
    with open(accounts_file, "r") as f:
        accounts = json.load(f)

    secrets = {
        "users": accounts["users"],
        "server_config": {
            "smtp_server": accounts["smtp_server"],
            "smtp_port": accounts["smtp_port"],
            "imap_server": accounts["imap_server"],
            "imap_port": accounts["imap_port"],
        },
    }

    secrets_file = os.path.join(script_dir, "secrets.json")
    with open(secrets_file, "w") as f:
        json.dump(secrets, f, indent=2)

    logger.info("Created secrets.json")
    return True


def main():
    logger.info("Starting DeltaChat account creation...")

    try:
        create_accounts_json()

        create_secrets_json()

        logger.info("Account creation completed successfully.")
        logger.info("MailHog accepts any email, so accounts are ready to use.")

        return True

    except Exception as e:
        logger.error("Failed to create accounts: %s", e)
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
