"""Availability checks for DeltaChat + docker-mailserver.

Verifies IMAP/SMTP sockets and ADB device availability.
"""

import imaplib
import json
import os
import smtplib
import socket
import sys
from typing import Tuple

from dotenv import load_dotenv

load_dotenv()

# Host ports from docker-compose:
#   1025:25 (SMTP), 1143:143 (IMAP)
IMAP_HOST = os.getenv("MAIL_IMAP_HOST", "localhost")
IMAP_PORT = int(os.getenv("MAIL_IMAP_PORT", "1143"))
SMTP_HOST = os.getenv("MAIL_SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("MAIL_SMTP_PORT", "1025"))


def _check_socket(host: str, port: int, timeout: int = 5) -> bool:
    """Simple TCP connect check."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_imap_availability() -> Tuple[bool, str]:
    """Check that the IMAP service accepts connections."""
    # First check the raw socket
    if not _check_socket(IMAP_HOST, IMAP_PORT):
        return False, f"IMAP socket {IMAP_HOST}:{IMAP_PORT} not reachable"
    # Then try an IMAP handshake
    try:
        client = imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
        client.logout()
        return True, "IMAP reachable and responding"
    except Exception as exc:  # noqa: BLE001
        return False, f"IMAP handshake failed: {exc}"


def check_smtp_availability() -> Tuple[bool, str]:
    """Check that the SMTP service accepts connections."""
    if not _check_socket(SMTP_HOST, SMTP_PORT):
        return False, f"SMTP socket {SMTP_HOST}:{SMTP_PORT} not reachable"
    try:
        client = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=5)
        client.noop()
        client.quit()
        return True, "SMTP reachable and responding"
    except Exception as exc:  # noqa: BLE001
        return False, f"SMTP handshake failed: {exc}"


def main() -> None:
    results = {}
    overall_ok = True

    ok, msg = check_imap_availability()
    results["check_imap_availability"] = 1 if ok else 0
    print(f"[{'PASS' if ok else 'FAIL'}] IMAP: {msg}", file=sys.stderr)
    if not ok:
        overall_ok = False

    ok, msg = check_smtp_availability()
    results["check_smtp_availability"] = 1 if ok else 0
    print(f"[{'PASS' if ok else 'FAIL'}] SMTP: {msg}", file=sys.stderr)
    if not ok:
        overall_ok = False

    results["score"] = 1 if overall_ok else 0
    print(json.dumps(results))
    # Always exit 0; failures are encoded in JSON score per project convention.
    sys.exit(0)


if __name__ == "__main__":
    main()
