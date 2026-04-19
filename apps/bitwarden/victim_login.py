#!/usr/bin/env python3
import json
import logging
import os
import sys

# Add project root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from apps.bitwarden.bw_workflows import bw_attempt_login  # noqa: E402
from utils.ui_utils import initialize_ui_automation  # noqa: E402


def setup_logging():
    logger = logging.getLogger("bitwarden_victim_login")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        formatter = "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"
        handler.setFormatter(logging.Formatter(formatter))
        logger.addHandler(handler)
    return logger


def main():
    logger = setup_logging()
    app_dir = os.path.dirname(os.path.abspath(__file__))
    metadata_path = os.path.join(app_dir, "metadata.json")

    try:
        with open(metadata_path, "r") as f:
            metadata = json.load(f)
    except Exception as e:
        logger.error("Failed to load metadata: %s", e)
        sys.exit(1)

    username = metadata.get("username")
    password = metadata.get("password")

    if not username or not password:
        logger.error("Victim credentials missing in metadata.json")
        sys.exit(1)

    logger.info("Initializing UI automation...")
    d = initialize_ui_automation()

    logger.info("Starting login attempt for victim: %s", username)
    try:
        # bw_attempt_login raises RuntimeError on failure
        bw_attempt_login(d, username, password)
        logger.info("Victim login successful.")
    except Exception as e:
        logger.error("Victim login failed: %s", e)
        # Standardized error message for RedTeamWorkflow expectation
        raise RuntimeError("victim login timed out") from e


if __name__ == "__main__":
    main()
