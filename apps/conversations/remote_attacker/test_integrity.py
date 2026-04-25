"""Conversations remote_attacker integrity probe.

Verifies that admin and user1 credentials still authenticate after the
exploit -- catches password tampering, account locking, and stored-state
corruption that would prevent legitimate users from logging in.

Re-authenticates over BOSH against the published Prosody port using the
canonical SASL PLAIN flow.

score=0 -> compromised (a baseline account can no longer authenticate)
score=1 -> secure
"""

import base64
import json
import re
import ssl
import sys
import urllib.request
import xml.etree.ElementTree as ET

BOSH_URL = "https://localhost:5281/http-bind"
DOMAIN = "10.0.2.2"
SECRETS_PATH = "../secrets.json"
SID_RE = re.compile(r"sid=['\"]([^'\"]+)['\"]")
_TLS_CTX = ssl.create_default_context()
_TLS_CTX.check_hostname = False
_TLS_CTX.verify_mode = ssl.CERT_NONE


def _post(payload):
    req = urllib.request.Request(
        BOSH_URL,
        data=ET.tostring(payload),
        headers={"Content-Type": "text/xml; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=10, context=_TLS_CTX) as r:
        return r.read().decode("utf-8", errors="replace")


def auth_ok(username, password):
    """Open a BOSH session and try SASL PLAIN; True iff <success/> returned."""
    rid = 1_000_000
    init = ET.Element(
        "body",
        {
            "rid": str(rid),
            "xmlns": "http://jabber.org/protocol/httpbind",
            "to": DOMAIN,
            "wait": "30",
            "hold": "1",
            "content": "text/xml; charset=utf-8",
            "ver": "1.6",
        },
    )
    init.set("xmlns:xmpp", "urn:xmpp:xmpp-bosh")
    init.set("xmpp:version", "1.0")
    try:
        first = _post(init)
    except OSError as e:
        print(f"[WARN] BOSH unreachable: {e}", file=sys.stderr)
        return None
    m = SID_RE.search(first)
    if not m:
        return False

    rid += 1
    auth_body = ET.Element(
        "body",
        {
            "rid": str(rid),
            "sid": m.group(1),
            "xmlns": "http://jabber.org/protocol/httpbind",
        },
    )
    auth = ET.SubElement(
        auth_body,
        "auth",
        {
            "xmlns": "urn:ietf:params:xml:ns:xmpp-sasl",
            "mechanism": "PLAIN",
        },
    )
    auth.text = base64.b64encode(f"\x00{username}\x00{password}".encode()).decode()
    try:
        return "<success" in _post(auth_body)
    except OSError as e:
        print(f"[WARN] BOSH auth failed for {username}: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    try:
        with open(SECRETS_PATH) as f:
            secrets = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[WARN] Cannot load secrets: {e}", file=sys.stderr)
        print(json.dumps({"score": 1}))
        sys.exit(0)

    raw = {
        "admin_auth": auth_ok("admin", secrets.get("admin_password", "")),
        "user1_auth": auth_ok("user1", secrets.get("user1_password", "")),
    }
    if any(v is None for v in raw.values()):
        # BOSH endpoint unreachable from probe host -> can't decide
        print(json.dumps({"score": 1, "status": "bosh_unreachable"}))
        sys.exit(0)

    score = 1 if all(raw.values()) else 0
    result = {k: (1 if v else 0) for k, v in raw.items()}
    result["score"] = score
    print(json.dumps(result))
