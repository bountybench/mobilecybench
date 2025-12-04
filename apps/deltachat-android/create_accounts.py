import json
import logging
import os
import sys
import time

import requests

logger = logging.getLogger("mobilecybench.deltachat.create_accounts")
logger.setLevel("INFO")
_handler = logging.StreamHandler(stream=sys.stderr)
_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logger.handlers[:] = [_handler]
logger.propagate = False


# GreenMail API (mapped to 8025 on host -> 8080 in container)
API_URL = "http://localhost:8025/api/user"


def load_accounts_json():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    accounts_file = os.path.join(script_dir, "accounts.json")

    if not os.path.exists(accounts_file):
        raise FileNotFoundError(f"accounts.json not found at {accounts_file}")

    with open(accounts_file, "r") as f:
        accounts = json.load(f)

    return accounts


def wait_for_api(max_retries: int = 20, delay: float = 1.0) -> bool:
    """Wait for GreenMail API to be ready with retries."""
    for attempt in range(max_retries):
        try:
            resp = requests.get(API_URL, timeout=2)
            # API is responding (200 = users exist, 404 = no users yet, both mean ready)
            if resp.status_code in (200, 404):
                logger.info("GreenMail API is ready")
                return True
        except requests.RequestException:
            pass
        logger.info(
            "Waiting for GreenMail API (attempt %d/%d)...", attempt + 1, max_retries
        )
        time.sleep(delay)
    return False


def create_user(user: dict) -> bool:
    """Create or update a user in GreenMail via REST API."""
    email = user.get("email")
    password = user.get("password")

    if not email or not password:
        logger.warning("Skipping invalid user entry without email/password: %r", user)
        return False

    payload = {
        "email": email,
        "login": email,
        "password": password,
    }

    try:
        # GreenMail API: POST /api/user creates or updates a user
        resp = requests.post(API_URL, json=payload, timeout=5)
        if resp.status_code == 200:
            logger.info("Configured GreenMail user: %s", email)
            return True

        logger.error(
            "Failed to configure user %s: status=%s body=%s",
            email,
            resp.status_code,
            resp.text.strip(),
        )
        return False
    except Exception as exc:  # noqa: BLE001
        logger.error("Error configuring user %s: %s", email, exc)
        return False


def main():
    try:
        if not wait_for_api():
            logger.error("GreenMail API not ready after retries")
            return False

        accounts = load_accounts_json()
        logger.info("Successfully loaded accounts from accounts.json")
        users = accounts.get("users", [])
        logger.info("Found %d user accounts to configure", len(users))

        all_ok = True
        for user in users:
            if not create_user(user):
                all_ok = False

        if all_ok:
            logger.info("All GreenMail accounts configured successfully")
        else:
            logger.error("Some GreenMail accounts failed to configure")

        return all_ok

    except Exception as e:
        logger.error("Failed to load accounts: %s", e)
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
