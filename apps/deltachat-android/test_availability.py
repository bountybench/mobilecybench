"""Availability checks for DeltaChat + GreenMail.

Verifies GreenMail API, IMAP/SMTP sockets, and ADB device availability.
"""

import imaplib
import json
import os
import shutil
import smtplib
import socket
import subprocess
import sys
from typing import Tuple

import requests
from dotenv import load_dotenv

load_dotenv()

# Host ports from docker-compose:
#   1025:3025 (SMTP), 1143:3143 (IMAP), 8025:8080 (HTTP/API)
GREENMAIL_API_URL = os.getenv("GREENMAIL_API_URL", "http://localhost:8025")
IMAP_HOST = os.getenv("GREENMAIL_IMAP_HOST", "localhost")
IMAP_PORT = int(os.getenv("GREENMAIL_IMAP_PORT", "1143"))
SMTP_HOST = os.getenv("GREENMAIL_SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("GREENMAIL_SMTP_PORT", "1025"))
ADB_BIN = os.getenv("ADB_BIN", "adb")


def _check_socket(host: str, port: int, timeout: int = 5) -> bool:
    """Simple TCP connect check."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_api_responsive() -> Tuple[bool, str]:
    """Check if GreenMail API is responsive on the mapped HTTP port."""
    try:
        # Try a readiness endpoint if available; otherwise any 2xx/4xx proves reachability.
        url = f"{GREENMAIL_API_URL}/api/service/readiness"
        resp = requests.get(url, timeout=5)
        return True, f"API reachable (status={resp.status_code})"
    except Exception as exc:  # noqa: BLE001
        return False, f"API unreachable: {exc}"


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


def check_adb_status() -> Tuple[bool, str]:
    """Check that adb is available and at least one device is attached."""
    if shutil.which(ADB_BIN) is None:
        return False, "adb binary not found"

    try:
        res = subprocess.run(
            [ADB_BIN, "devices"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"adb devices failed: {exc}"

    if res.returncode != 0:
        return False, f"adb devices exited with {res.returncode}"

    # Skip header line and look for any line ending with "\tdevice"
    lines = res.stdout.splitlines()[1:]
    has_device = any(line.strip().endswith("\tdevice") for line in lines)
    if not has_device:
        return False, "no adb device detected"

    return True, "adb device detected"


def main() -> None:
    results = {}
    overall_ok = True

    ok, msg = check_api_responsive()
    results["check_api_responsive"] = 1 if ok else 0
    print(f"[{'PASS' if ok else 'FAIL'}] API: {msg}", file=sys.stderr)
    if not ok:
        overall_ok = False

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

    ok, msg = check_adb_status()
    results["check_adb_status"] = 1 if ok else 0
    print(f"[{'PASS' if ok else 'FAIL'}] ADB: {msg}", file=sys.stderr)
    if not ok:
        overall_ok = False

    results["score"] = 1 if overall_ok else 0
    print(json.dumps(results))
    # Always exit 0; failures are encoded in JSON score per project convention.
    sys.exit(0)


if __name__ == "__main__":
    main()
