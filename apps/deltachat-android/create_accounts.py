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


def main():
    try:
        accounts = load_accounts_json()
        logger.info("Successfully loaded accounts from accounts.json")
        logger.info("Found %d user accounts", len(accounts.get("users", [])))
        return True

    except Exception as e:
        logger.error("Failed to load accounts: %s", e)
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
