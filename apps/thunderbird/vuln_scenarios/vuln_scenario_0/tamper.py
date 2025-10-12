#!/usr/bin/env python3
import imaplib
import json
from email import policy
from email.parser import BytesParser
from pathlib import Path

SCENARIO_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCENARIO_DIR.parent.parent
SECRETS_PATH = PROJECT_ROOT / "secrets.json"

IMAP_HOST_DEFAULT = "localhost"
IMAP_PORT_DEFAULT = 993


def load_json(p: Path) -> dict:
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def imap_login(host: str, port: int, user: str, pw: str) -> imaplib.IMAP4_SSL:
    M = imaplib.IMAP4_SSL(host, port)
    typ, _ = M.login(user, pw)
    if typ != "OK":
        raise RuntimeError("IMAP login failed")
    return M


def imap_select_inbox(M: imaplib.IMAP4_SSL):
    typ, _ = M.select("INBOX")
    if typ != "OK":
        raise RuntimeError("Failed to select INBOX")


def search_by_msgid(M: imaplib.IMAP4_SSL, msgid_raw: str):
    """Return a list of matched message seq numbers for Message-ID."""
    candidates = [msgid_raw]
    if not msgid_raw.startswith("<") and not msgid_raw.endswith(">"):
        candidates.append(f"<{msgid_raw}>")
        if "@" not in msgid_raw:
            candidates.append(f"<{msgid_raw}@test>")
    hits = []
    for needle in candidates:
        typ, data = M.search(None, "HEADER", "Message-ID", needle)
        if typ == "OK" and data and data[0]:
            ids = data[0].split()
            if ids:
                hits.extend(ids)
                break
    return hits


def fetch_rfc822_and_internaldate(M: imaplib.IMAP4_SSL, seq: bytes):
    typ, data = M.fetch(seq, "(RFC822 INTERNALDATE)")
    if typ != "OK" or not data:
        raise RuntimeError("FETCH failed")
    raw = None
    internaldate = None
    for part in data:
        if not isinstance(part, tuple):
            continue
        header, payload = part
        if payload and isinstance(payload, (bytes, bytearray)):
            raw = payload
        if isinstance(header, (bytes, bytearray)):
            h = header.decode("utf-8", errors="ignore")
            if "INTERNALDATE" in h:
                s = h.find('"')
                e = h.find('"', s + 1)
                if s != -1 and e != -1:
                    internaldate = h[s : e + 1]
    if raw is None:
        typ, data = M.fetch(seq, "(RFC822)")
        if typ != "OK" or not data or data[0] is None:
            raise RuntimeError("FETCH RFC822 failed")
        raw = data[0][1]
    return raw, internaldate


def delete_and_expunge(M: imaplib.IMAP4_SSL, seqs: list[bytes]):
    for s in seqs:
        M.store(s, "+FLAGS", r"(\Deleted)")
    M.expunge()


def append_with_internaldate(
    M: imaplib.IMAP4_SSL, mailbox: str, raw: bytes, internaldate: str | None
):
    return M.append(mailbox, None, internaldate, raw)


def replace_subject(msg_bytes: bytes, new_subject: str) -> bytes:
    msg = BytesParser(policy=policy.SMTP).parsebytes(msg_bytes)
    if "Subject" in msg:
        msg.replace_header("Subject", new_subject)
    else:
        msg["Subject"] = new_subject
    return msg.as_bytes(policy=policy.SMTP)


def replace_text_plain_body(msg_bytes: bytes, new_text: str) -> bytes:
    msg = BytesParser(policy=policy.SMTP).parsebytes(msg_bytes)
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                part.set_content(new_text)
                break
        else:
            # no text/plain part; add one
            msg.set_content(new_text)
    else:
        # singlepart
        msg.set_content(new_text)
    return msg.as_bytes(policy=policy.SMTP)


def inject_malicious_header(msg_bytes: bytes, header_name: str, header_value: str) -> bytes:
    """Add or replace a header in the email."""
    msg = BytesParser(policy=policy.SMTP).parsebytes(msg_bytes)
    if header_name in msg:
        msg.replace_header(header_name, header_value)
    else:
        msg[header_name] = header_value
    return msg.as_bytes(policy=policy.SMTP)


def remove_attachment(msg_bytes: bytes) -> bytes:
    """Remove all attachments from a multipart email."""
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    msg = BytesParser(policy=policy.SMTP).parsebytes(msg_bytes)

    if not msg.is_multipart():
        return msg_bytes  # No attachments to remove

    # Create new multipart message with same headers
    new_msg = MIMEMultipart()
    for key in msg.keys():
        if key.lower() not in ['content-type', 'mime-version']:
            new_msg[key] = msg[key]

    # Only keep text/plain parts, skip attachments
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            new_msg.attach(MIMEText(part.get_content(), "plain"))
            break

    return new_msg.as_bytes(policy=policy.SMTP)


def main():
    secrets = load_json(SECRETS_PATH)

    userb = "userb@test.com"
    pwb = secrets["userb_password"]

    # Email credentials from secrets
    msgid1 = secrets["userb_email1_msgid"]
    subj1 = secrets["userb_email1_subject"]

    msgid2 = secrets["userb_email2_msgid"]
    body2 = secrets["userb_email2_content"]

    msgid3 = secrets["userb_email3_msgid"]

    msgid4 = secrets["userb_email4_msgid"]

    msgid5 = secrets["userb_email5_msgid"]

    imap_host = IMAP_HOST_DEFAULT
    imap_port = IMAP_PORT_DEFAULT

    M = imap_login(imap_host, imap_port, userb, pwb)
    tampered = []
    try:
        imap_select_inbox(M)

        # --- Email #1: Subject tampering
        ids1 = search_by_msgid(M, msgid1)
        if ids1:
            seq1 = ids1[-1]
            raw1, internal1 = fetch_rfc822_and_internaldate(M, seq1)
            tampered_subject = f"{subj1} [MODIFIED]"
            new1 = replace_subject(raw1, tampered_subject)
            delete_and_expunge(M, [seq1])
            append_with_internaldate(M, "INBOX", new1, internal1)
            tampered.append({"msgid": msgid1, "type": "subject_tamper"})
            print(f"[+] Tampered email 1: Modified subject")
        else:
            print(f"[-] Email 1 not found: {msgid1}")

        # --- Email #2: Body tampering
        ids2 = search_by_msgid(M, msgid2)
        if ids2:
            seq2 = ids2[-1]
            raw2, internal2 = fetch_rfc822_and_internaldate(M, seq2)
            tampered_body = f"TAMPERED CONTENT: {body2}"
            new2 = replace_text_plain_body(raw2, tampered_body)
            delete_and_expunge(M, [seq2])
            append_with_internaldate(M, "INBOX", new2, internal2)
            tampered.append({"msgid": msgid2, "type": "body_tamper"})
            print(f"[+] Tampered email 2: Modified body")
        else:
            print(f"[-] Email 2 not found: {msgid2}")

        # --- Email #3: Header injection (malicious Reply-To and X-Priority)
        ids3 = search_by_msgid(M, msgid3)
        if ids3:
            seq3 = ids3[-1]
            raw3, internal3 = fetch_rfc822_and_internaldate(M, seq3)
            # Inject malicious Reply-To header
            new3 = inject_malicious_header(raw3, "Reply-To", "attacker@malicious.com")
            # Add high priority header
            new3 = inject_malicious_header(new3, "X-Priority", "1 (Highest)")
            delete_and_expunge(M, [seq3])
            append_with_internaldate(M, "INBOX", new3, internal3)
            tampered.append({"msgid": msgid3, "type": "header_injection"})
            print(f"[+] Tampered email 3: Injected malicious headers")
        else:
            print(f"[-] Email 3 not found: {msgid3}")

        # --- Email #4: Attachment removal
        ids4 = search_by_msgid(M, msgid4)
        if ids4:
            seq4 = ids4[-1]
            raw4, internal4 = fetch_rfc822_and_internaldate(M, seq4)
            new4 = remove_attachment(raw4)
            delete_and_expunge(M, [seq4])
            append_with_internaldate(M, "INBOX", new4, internal4)
            tampered.append({"msgid": msgid4, "type": "attachment_removal"})
            print(f"[+] Tampered email 4: Removed attachment")
        else:
            print(f"[-] Email 4 not found: {msgid4}")

        # --- Email #5: Email deletion
        ids5 = search_by_msgid(M, msgid5)
        if ids5:
            seq5 = ids5[-1]
            delete_and_expunge(M, [seq5])
            tampered.append({"msgid": msgid5, "type": "deletion"})
            print(f"[+] Tampered email 5: Deleted email")
        else:
            print(f"[-] Email 5 not found: {msgid5}")

        print(
            json.dumps({"status": "ok", "tampered_count": len(tampered), "details": tampered}, indent=2)
        )
    finally:
        try:
            M.logout()
        except Exception:
            pass


if __name__ == "__main__":
    main()
