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
                "password": "plusminuszero",
                "name": "Test User 1",
            },
            {
                "email": "user2@deltachat.test",
                "password": "lithiumberylium",
                "name": "Test User 2",
            },
            {
                "email": "user3@deltachat.test",
                "password": "nobellaureate1776",
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

    return accounts



def main():
    try:
        create_accounts_json()
        return True

    except Exception as e:
        logger.error("Failed to create accounts: %s", e)
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
