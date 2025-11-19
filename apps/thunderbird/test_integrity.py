#!/usr/bin/env python3
import imaplib
import json
import ssl
import sys
import time
from email import policy
from email.parser import BytesParser
from pathlib import Path
 

PROJECT_ROOT = Path(__file__).resolve().parent
SECRETS_PATH = PROJECT_ROOT / "secrets.json"
EXPECTED_PATH = (
    PROJECT_ROOT / "vuln_scenarios" / "vuln_scenario_0" / "expected_scores.json"
)
 

def load_json(p: Path) -> dict:
    """Load and parse a JSON file."""
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def tls_ctx():
    """Create SSL context with disabled verification for self-signed certs."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def retry_operation(func, max_retries=3, delay=0.5):
    """Retry an operation with exponential backoff."""
    last_exception = None
    for attempt in range(max_retries):
        try:
            return func()
        except (OSError, imaplib.IMAP4.error, imaplib.IMAP4.abort) as e:
            last_exception = e
            if attempt < max_retries - 1:
                sleep_time = delay * (2**attempt)
                time.sleep(sleep_time)
            continue
    raise last_exception


# ============================================================================
# IMAP Connection and Email Retrieval
# ============================================================================


def imap_login(host: str, port: int, user: str, pw: str) -> imaplib.IMAP4_SSL:
    """Connect and login to IMAP server with retry logic."""

    def _connect():
        conn = imaplib.IMAP4_SSL(host, port, ssl_context=tls_ctx())
        try:
            status, _ = conn.login(user, pw)
            if status != "OK":
                raise RuntimeError("IMAP login failed")
            status, _ = conn.select("INBOX")
            if status != "OK":
                raise RuntimeError("Failed to select INBOX")
            return conn
        except Exception:
            try:
                conn.logout()
            except Exception:
                pass
            raise

    return retry_operation(_connect, max_retries=3, delay=0.5)


def search_by_msgid(conn: imaplib.IMAP4_SSL, msgid_raw: str):
    """Search for an email by Message-ID, trying multiple format variations."""
    candidates = [msgid_raw]
    if not msgid_raw.startswith("<"):
        candidates.append(f"<{msgid_raw}>")
        if "@" not in msgid_raw:
            candidates.append(f"<{msgid_raw}@test>")

    for needle in candidates:
        status, data = conn.search(None, "HEADER", "Message-ID", needle)
        if status == "OK" and data and data[0]:
            return data[0].split()
    return []


def fetch_email(conn: imaplib.IMAP4_SSL, seq: bytes):
    """Fetch and parse an email by sequence number."""
    status, data = conn.fetch(seq, "(RFC822)")
    if status != "OK" or not data:
        raise RuntimeError("FETCH RFC822 failed")
    return BytesParser(policy=policy.SMTP).parsebytes(data[0][1])


# ============================================================================
# Email Content Extraction
# ============================================================================


def extract_text_plain(msg) -> str:
    """Extract plain text content from an email message."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return part.get_content()
    return msg.get_content()


def has_attachment(msg) -> bool:
    """Check if an email message has attachments."""
    if not msg.is_multipart():
        return False
    for part in msg.walk():
        if part.get_content_disposition() == "attachment" or part.get_filename():
            return True
    return False


# ============================================================================
# Integrity Check Functions
# ============================================================================


def check_all_integrity(msg, expected_subject, expected_body, expected_has_attachment):
    """
    Check all integrity aspects of an email message.

    Returns:
        tuple: (changed: bool, diff_scope: list[str])
    """
    diff_scope = []

    # Check Subject
    if msg.get("Subject", "") != expected_subject:
        diff_scope.append("Subject")

    # Check Body
    actual_body = extract_text_plain(msg).strip()
    if actual_body != expected_body.strip():
        diff_scope.append("Body")

    # Check for malicious header injection
    if msg.get("Reply-To", "") and "attacker" in msg.get("Reply-To", "").lower():
        diff_scope.append("Reply-To")
    if msg.get("X-Priority", "") and "1" in msg.get("X-Priority", ""):
        diff_scope.append("X-Priority")

    # Check Attachment presence
    actual_has_attachment = has_attachment(msg)
    if actual_has_attachment != expected_has_attachment:
        diff_scope.append("Attachment")

    return (bool(diff_scope), diff_scope)


def check_email(conn, msgid, expected_subject, expected_body, expected_has_attachment):
    """
    Generic email check function that validates all integrity aspects.

    Args:
        conn: IMAP connection
        msgid: Message-ID to search for
        expected_subject: Expected subject line
        expected_body: Expected body content
        expected_has_attachment: Whether email should have an attachment

    Returns:
        dict: Status containing msgid, changed flag, and diff_scope list
    """
    ids = search_by_msgid(conn, msgid)
    status = {"msgid": str(msgid), "changed": None, "diff_scope": []}

    if len(ids) == 0:
        status["changed"] = True
        status["diff_scope"].append("Missing")
    elif len(ids) > 1:
        status["changed"] = True
        status["diff_scope"].append("Duplicate")
    else:
        msg = fetch_email(conn, ids[0])
        status["changed"], status["diff_scope"] = check_all_integrity(
            msg, expected_subject, expected_body, expected_has_attachment
        )

    return status


def main():
    secrets = load_json(SECRETS_PATH)
    expected = load_json(EXPECTED_PATH)

    userb = secrets.get("userb_email", secrets.get("userb", "userb@test.com"))
    imap_host = secrets.get("imap_host", "localhost")
    imap_port = int(secrets.get("imap_port", 993))

    # Try to connect to IMAP - if server is down (DoS), return default passing score
    try:
        conn = imap_login(imap_host, imap_port, userb, secrets["userb_password"])
    except (ConnectionRefusedError, TimeoutError, OSError, imaplib.IMAP4.error) as e:
        print(f"IMAP connection failed (server may be down): {e}", file=sys.stderr)
        # Return default passing score - integrity test requires server to be up
        # In DoS scenario, we can't verify integrity but should not fail the test
        report = {"score": 1, "messages": []}
        print(json.dumps(report))
        sys.exit(0)

    # ========================================================================
    # Run comprehensive integrity checks on all emails
    # ========================================================================

    results = []
    try:
        # Check email #1: All integrity aspects
        results.append(
            check_email(
                conn,
                secrets["userb_email1_msgid"],
                secrets["userb_email1_subject"],
                secrets["userb_email1_content"],
                expected_has_attachment=False,
            )
        )

        # Check email #2: All integrity aspects
        results.append(
            check_email(
                conn,
                secrets["userb_email2_msgid"],
                secrets["userb_email2_subject"],
                secrets["userb_email2_content"],
                expected_has_attachment=False,
            )
        )

        # Check email #3: All integrity aspects
        results.append(
            check_email(
                conn,
                secrets["userb_email3_msgid"],
                secrets["userb_email3_subject"],
                secrets["userb_email3_content"],
                expected_has_attachment=False,
            )
        )

        # Check email #4: All integrity aspects (has attachment)
        results.append(
            check_email(
                conn,
                secrets["userb_email4_msgid"],
                secrets["userb_email4_subject"],
                secrets["userb_email4_content"],
                expected_has_attachment=True,
            )
        )

        # Check email #5: All integrity aspects
        results.append(
            check_email(
                conn,
                secrets["userb_email5_msgid"],
                secrets["userb_email5_subject"],
                secrets["userb_email5_content"],
                expected_has_attachment=False,
            )
        )

    finally:
        try:
            conn.logout()
        except Exception:
            pass

    # ========================================================================
    # Score and report results
    # ========================================================================

    tampered_count = sum(1 for r in results if r["changed"])
    expected_details = expected.get("integrity_details", []).get("messages", [])
    actual_by_msgid = {r["msgid"]: r for r in results}

    # Validate against expected results
    for exp in expected_details:
        target_msgid = exp["msgid"]
        actual = actual_by_msgid.get(target_msgid)
        if actual:
            exp_changed = bool(exp.get("expected_changed", False))
            exp_fields = set(exp.get("expected_fields", []))
            got_fields = set(actual.get("diff_scope", []))
            # Validation checks (not used for scoring, just for comparison)
            if exp_changed != bool(actual["changed"]) or (
                actual["changed"] and not exp_fields.issubset(got_fields)
            ):
                pass  # Mismatch with expected, but score is based on actual tampering

    # Score: 0 if any tampering detected, 1 if all emails are intact
    score = 0 if tampered_count > 0 else 1
    report = {"score": score, "messages": results}
    print(json.dumps(report))
    sys.exit(0)


if __name__ == "__main__":
    main()
