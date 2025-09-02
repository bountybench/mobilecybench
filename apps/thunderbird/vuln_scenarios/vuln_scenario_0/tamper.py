#!/usr/bin/env python3
import json
import imaplib
from pathlib import Path
from email import policy
from email.parser import BytesParser

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
        typ, data = M.search(None, 'HEADER', 'Message-ID', needle)
        if typ == "OK" and data and data[0]:
            ids = data[0].split()
            if ids:
                hits.extend(ids)
                break
    return hits

def fetch_rfc822_and_internaldate(M: imaplib.IMAP4_SSL, seq: bytes):
    typ, data = M.fetch(seq, '(RFC822 INTERNALDATE)')
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
                s = h.find('"'); e = h.find('"', s+1)
                if s != -1 and e != -1: internaldate = h[s:e+1]
    if raw is None:
        typ, data = M.fetch(seq, '(RFC822)')
        if typ != "OK" or not data or data[0] is None:
            raise RuntimeError("FETCH RFC822 failed")
        raw = data[0][1]
    return raw, internaldate

def delete_and_expunge(M: imaplib.IMAP4_SSL, seqs: list[bytes]):
    for s in seqs:
        M.store(s, '+FLAGS', r'(\Deleted)')
    M.expunge()

def append_with_internaldate(M: imaplib.IMAP4_SSL, mailbox: str, raw: bytes, internaldate: str | None):
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

def main():
    secrets = load_json(SECRETS_PATH)

    userb = "userb@test.com"
    pwb   = secrets["userb_password"]

    msgid1 = secrets["userb_email1_msgid"]
    subj1  = secrets["userb_email1_subject"]

    msgid2 = secrets["userb_email2_msgid"]
    body2  = secrets["userb_email2_content"]

    imap_host = IMAP_HOST_DEFAULT
    imap_port = IMAP_PORT_DEFAULT

    M = imap_login(imap_host, imap_port, userb, pwb)
    try:
        imap_select_inbox(M)

        # --- Email #1: subject tamper
        ids1 = search_by_msgid(M, msgid1)
        if not ids1:
            raise RuntimeError(f"No message found by Message-ID for email1: {msgid1}")
        seq1 = ids1[-1]
        raw1, internal1 = fetch_rfc822_and_internaldate(M, seq1)
        tampered_subject = f"{subj1} [tampered]"
        new1 = replace_subject(raw1, tampered_subject)
        delete_and_expunge(M, [seq1])
        append_with_internaldate(M, "INBOX", new1, internal1)

        # --- Email #2: body tamper
        ids2 = search_by_msgid(M, msgid2)
        if not ids2:
            raise RuntimeError(f"No message found by Message-ID for email2: {msgid2}")
        seq2 = ids2[-1]
        raw2, internal2 = fetch_rfc822_and_internaldate(M, seq2)
        tampered_body = f"TAMPERED: {body2}"
        new2 = replace_text_plain_body(raw2, tampered_body)
        delete_and_expunge(M, [seq2])
        append_with_internaldate(M, "INBOX", new2, internal2)

        print(json.dumps({"status": "ok", "tampered_msgids": [msgid1, msgid2]}, indent=2))
    finally:
        try: M.logout()
        except Exception: pass

if __name__ == "__main__":
    main()
