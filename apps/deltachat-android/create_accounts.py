import json
import logging
import os
import subprocess
import sys
import time

logger = logging.getLogger("mobilecybench.deltachat.create_accounts")
logger.setLevel("INFO")
_handler = logging.StreamHandler(stream=sys.stderr)
_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logger.handlers[:] = [_handler]
logger.propagate = False

CONTAINER_NAME = "deltachat-mailserver"


def load_accounts_json():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    accounts_file = os.path.join(script_dir, "accounts.json")

    if not os.path.exists(accounts_file):
        raise FileNotFoundError(f"accounts.json not found at {accounts_file}")

    with open(accounts_file, "r") as f:
        accounts = json.load(f)

    return accounts


def wait_for_container(max_retries: int = 30, delay: float = 2.0) -> bool:
    """Wait for docker-mailserver container to be ready."""
    for attempt in range(max_retries):
        try:
            # Check if dovecot is running inside the container
            result = subprocess.run(
                ["docker", "exec", CONTAINER_NAME, "test", "-f", "/var/run/dovecot/master.pid"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                logger.info("docker-mailserver is ready")
                return True
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            pass
        logger.info(
            "Waiting for docker-mailserver (attempt %d/%d)...", attempt + 1, max_retries
        )
        time.sleep(delay)
    return False


def create_user(user: dict) -> bool:
    """Create a user in docker-mailserver via setup command."""
    email = user.get("email")
    password = user.get("password")

    if not email or not password:
        logger.warning("Skipping invalid user entry without email/password: %r", user)
        return False

    try:
        # docker-mailserver uses setup email add command
        result = subprocess.run(
            ["docker", "exec", CONTAINER_NAME, "setup", "email", "add", email, password],
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        if result.returncode == 0:
            logger.info("Configured docker-mailserver user: %s", email)
            return True
        
        # Check if user already exists (exit code 1 with specific message)
        if "already exists" in result.stderr.lower() or "already exists" in result.stdout.lower():
            logger.info("User %s already exists, updating password...", email)
            # Try to update the user's password
            update_result = subprocess.run(
                ["docker", "exec", CONTAINER_NAME, "setup", "email", "update", email, password],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if update_result.returncode == 0:
                logger.info("Updated password for user: %s", email)
                return True
        
        logger.error(
            "Failed to configure user %s: returncode=%s stdout=%s stderr=%s",
            email,
            result.returncode,
            result.stdout.strip(),
            result.stderr.strip(),
        )
        return False
    except subprocess.TimeoutExpired:
        logger.error("Timeout configuring user %s", email)
        return False
    except Exception as exc:
        logger.error("Error configuring user %s: %s", email, exc)
        return False


def main():
    try:
        if not wait_for_container():
            logger.error("docker-mailserver not ready after retries")
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
            logger.info("All docker-mailserver accounts configured successfully")
        else:
            logger.error("Some docker-mailserver accounts failed to configure")

        return all_ok

    except Exception as e:
        logger.error("Failed to load accounts: %s", e)
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
