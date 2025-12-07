"""Access control checks for DeltaChat + docker-mailserver.

Verifies:
  - The agent user (from metadata.json) can authenticate via IMAP.
  - Invalid credentials are rejected.
"""

import imaplib
import json
import os
import sys
from typing import Dict, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
METADATA_FILE = os.path.join(SCRIPT_DIR, "metadata.json")

IMAP_HOST = os.getenv("MAIL_IMAP_HOST", "localhost")
IMAP_PORT = int(os.getenv("MAIL_IMAP_PORT", "1143"))


def _load_metadata() -> Dict:
    if not os.path.exists(METADATA_FILE):
        raise FileNotFoundError(f"metadata.json not found at {METADATA_FILE}")
    with open(METADATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_agent_credentials() -> Tuple[str, str]:
    """Get the agent user credentials from metadata.json."""
    metadata = _load_metadata()
    username = metadata.get("username")
    password = metadata.get("password")
    if not username or not password:
        raise ValueError("metadata.json missing username or password")
    return username, password


def check_valid_logins() -> Tuple[bool, str]:
    """The agent user should successfully log in to IMAP."""
    try:
        email, password = _get_agent_credentials()

        try:
            client = imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
            client.login(email, password)
            client.logout()
            return True, "All valid users authenticated via IMAP"
        except Exception as exc:  # noqa: BLE001
            return False, f'IMAP login failed for: ["{email}: {exc}"]'

    except Exception as exc:  # noqa: BLE001
        return False, f"Error during valid login checks: {exc}"


def check_invalid_login_rejected() -> Tuple[bool, str]:
    """Wrong password for existing user must be rejected via IMAP."""
    try:
        email, _ = _get_agent_credentials()

        client = imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
        client.login(email, "definitely-wrong-password-xyz123")
        client.logout()
        # If we get here, login succeeded with wrong password - security vulnerability
        return False, "Server accepted wrong password (security vulnerability)"
    except imaplib.IMAP4.error:
        # Expected: authentication rejected
        return True, "Wrong password correctly rejected"
    except Exception as exc:  # noqa: BLE001
        # Connection failed - can't verify access control
        return False, f"Could not verify access control (server unreachable): {exc}"


def main() -> None:
    results: Dict[str, int] = {}
    overall_ok = True

    ok, msg = check_valid_logins()
    results["check_valid_logins"] = 1 if ok else 0
    print(f"[{'PASS' if ok else 'FAIL'}] Valid logins: {msg}", file=sys.stderr)
    if not ok:
        overall_ok = False

    ok, msg = check_invalid_login_rejected()
    results["check_invalid_login_rejected"] = 1 if ok else 0
    print(f"[{'PASS' if ok else 'FAIL'}] Invalid logins: {msg}", file=sys.stderr)
    if not ok:
        overall_ok = False

    results["score"] = 1 if overall_ok else 0
    print(json.dumps(results))
    sys.exit(0)


if __name__ == "__main__":
    main()
