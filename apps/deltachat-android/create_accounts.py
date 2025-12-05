"""
Verify mail accounts are configured for docker-mailserver.

This script checks that the postfix-accounts.cf file exists and contains
the expected user accounts. Accounts are pre-configured in setup.sh before
the container starts.
"""

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


def load_accounts_json():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    accounts_file = os.path.join(script_dir, "accounts.json")

    if not os.path.exists(accounts_file):
        raise FileNotFoundError(f"accounts.json not found at {accounts_file}")

    with open(accounts_file, "r") as f:
        accounts = json.load(f)

    return accounts


def verify_accounts_config() -> bool:
    """Verify that the postfix-accounts.cf file exists with expected users."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_file = os.path.join(script_dir, "docker-data", "config", "postfix-accounts.cf")
    
    if not os.path.exists(config_file):
        logger.error("postfix-accounts.cf not found at %s", config_file)
        logger.error("Run setup.sh to create the mail accounts configuration")
        return False
    
    with open(config_file, "r") as f:
        content = f.read()
    
    accounts = load_accounts_json()
    users = accounts.get("users", [])
    
    all_ok = True
    for user in users:
        email = user.get("email")
        if email and email in content:
            logger.info("Found account configuration for: %s", email)
        else:
            logger.error("Missing account configuration for: %s", email)
            all_ok = False
    
    return all_ok


def main():
    try:
        if verify_accounts_config():
            logger.info("All mail accounts are configured")
            return True
        else:
            logger.error("Some mail accounts are missing from configuration")
            return False

    except Exception as e:
        logger.error("Failed to verify accounts: %s", e)
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
