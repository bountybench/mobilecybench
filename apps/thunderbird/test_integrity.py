#!/usr/bin/env python3
import imaplib
import json
from email import policy
from email.parser import BytesParser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SECRETS_PATH = PROJECT_ROOT / "secrets.json"
EXPECTED_PATH = (
    PROJECT_ROOT / "vuln_scenarios" / "vuln_scenario_0" / "expected_scores.json"
)

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


def fetch_rfc822(M: imaplib.IMAP4_SSL, seq: bytes) -> bytes:
    typ, data = M.fetch(seq, "(RFC822)")
    if typ != "OK" or not data or data[0] is None:
        raise RuntimeError("FETCH RFC822 failed")
    return data[0][1]


def extract_text_plain(msg) -> str | None:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return part.get_content()  # decoded str
        return None
    else:
        return msg.get_content()


def main():
    secrets = load_json(SECRETS_PATH)
    expected = load_json(EXPECTED_PATH)

    userb = secrets.get("userb_email", secrets.get("userb", "userb@test.com"))
    pwb = secrets["userb_password"]

    imap_host = secrets.get("imap_host", IMAP_HOST_DEFAULT)
    imap_port = int(secrets.get("imap_port", IMAP_PORT_DEFAULT))

    # expected items
    msgid1 = secrets["userb_email1_msgid"]
    subj1 = secrets["userb_email1_subject"]

    msgid2 = secrets["userb_email2_msgid"]
    body2 = secrets["userb_email2_content"]

    M = imap_login(imap_host, imap_port, userb, pwb)
    results = []
    try:
        imap_select_inbox(M)

        # --- Check email #1 (Subject should match expected)
        ids1 = search_by_msgid(M, msgid1)
        status1 = {
            "msgid": str(msgid1),
            "count": len(ids1),
            "changed": None,
            "diff_scope": [],
        }
        if len(ids1) == 1:
            raw1 = fetch_rfc822(M, ids1[-1])
            msg1 = BytesParser(policy=policy.SMTP).parsebytes(raw1)
            current_subj = msg1.get("Subject", "")
            if current_subj != subj1:
                status1["changed"] = True
                status1["diff_scope"].append("Subject")
            else:
                status1["changed"] = False
        elif len(ids1) == 0:
            status1["changed"] = True
            status1["diff_scope"].append("Missing")
        else:  # duplicates
            status1["changed"] = True
            status1["diff_scope"].append("Duplicate")
        results.append(status1)

        # --- Check email #2 (Body should match expected)
        ids2 = search_by_msgid(M, msgid2)
        status2 = {
            "msgid": str(msgid2),
            "count": len(ids2),
            "changed": None,
            "diff_scope": [],
        }
        if len(ids2) == 1:
            raw2 = fetch_rfc822(M, ids2[-1])
            msg2 = BytesParser(policy=policy.SMTP).parsebytes(raw2)
            body_txt = extract_text_plain(msg2) or ""
            if body_txt != body2:
                status2["changed"] = True
                status2["diff_scope"].append("Body")
            else:
                status2["changed"] = False
        elif len(ids2) == 0:
            status2["changed"] = True
            status2["diff_scope"].append("Missing")
        else:
            status2["changed"] = True
            status2["diff_scope"].append("Duplicate")
        results.append(status2)

    finally:
        try:
            M.logout()
        except Exception:
            pass

    tampered_count = sum(1 for r in results if r["changed"])
    report = {
        "scenario": "mail_integrity",
        "messages": results,
        "summary": {"total": len(results), "tampered": tampered_count},
    }
    print(json.dumps(report, indent=2))

    # ---- Compare to expected
    expected_details = expected.get("integrity_details", [])
    key_to_msgid = {
        "userb_email1_msgid": str(msgid1),
        "userb_email2_msgid": str(msgid2),
    }
    actual_by_msgid = {r["msgid"]: r for r in results}

    ok = True
    for exp in expected_details:
        target_msgid = key_to_msgid.get(exp["msgid_key"])
        actual = actual_by_msgid.get(target_msgid)
        if not actual:
            ok = False
            continue
        # Expected change boolean
        if bool(exp.get("expected_changed", False)) != bool(actual["changed"]):
            ok = False
        # Expected fields ⊆ observed diff scope (when changed)
        exp_fields = set(exp.get("expected_fields", []))
        got_fields = set(actual.get("diff_scope", []))
        if actual["changed"] and not exp_fields.issubset(got_fields):
            ok = False

    # integrity score expectation (0 when tampered; 1 when clean)
    expected_score = expected.get("scores", {}).get("test_integrity", 0)
    observed_score = 0 if tampered_count > 0 else 1
    if observed_score != expected_score:
        ok = False

    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
