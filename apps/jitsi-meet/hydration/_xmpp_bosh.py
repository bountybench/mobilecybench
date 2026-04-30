"""Shared helper: minimal raw-BOSH MUC client for chat-history injection.

Reuses the same transport `apps/jitsi-meet/prosody_utils.py:bosh_plain_login`
uses for confidentiality probes — XMPP-over-BOSH via `requests`. No
slixmpp / aioxmpp dependency. Fail-closed: every BOSH error raises.

Flow per sender: BOSH session init → SASL PLAIN → stream restart →
resource bind → MUC presence to room/nick → groupchat message stanzas
→ MUC unavailable presence → BOSH terminate.
"""

from __future__ import annotations

import base64
import os
import random
import time
import xml.etree.ElementTree as ET

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

XMPP_DOMAIN = os.environ.get("XMPP_DOMAIN", "auth.meet.jitsi")
BOSH_URL = os.environ.get("BOSH_URL", "http://localhost:5280/http-bind")

NS_BOSH = "http://jabber.org/protocol/httpbind"
NS_XBOSH = "urn:xmpp:xbosh"
NS_SASL = "urn:ietf:params:xml:ns:xmpp-sasl"
NS_BIND = "urn:ietf:params:xml:ns:xmpp-bind"
NS_CLIENT = "jabber:client"
NS_MUC = "http://jabber.org/protocol/muc"


class BoshError(Exception):
    pass


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


class BoshMucClient:
    def __init__(
        self,
        bosh_url: str = BOSH_URL,
        domain: str = XMPP_DOMAIN,
        *,
        verify_ssl: bool = False,
        timeout: int | None = None,
        wait: int | None = None,
    ):
        self.bosh_url = bosh_url
        self.domain = domain
        self.verify_ssl = verify_ssl
        # BOSH is a long-polling protocol.  The previous client opened the
        # session with wait=60 while using an 8s requests timeout, which can
        # fail in CI whenever Prosody legally holds an empty stanza response
        # instead of replying immediately.  Keep the long-poll window short for
        # hydration (we only need to inject messages) and make the HTTP timeout
        # comfortably larger than the advertised BOSH wait.
        self.wait = wait if wait is not None else int(os.environ.get("BOSH_WAIT", "1"))
        self.timeout = (
            timeout
            if timeout is not None
            else int(os.environ.get("BOSH_TIMEOUT", str(max(self.wait + 8, 10))))
        )
        self.sid: str | None = None
        self.rid = random.randint(1_000_000, 9_999_999)
        self.full_jid: str | None = None

    def _post(self, body_attrs: dict, payload_xml: str = "") -> str:
        attrs = " ".join(f'{k}="{v}"' for k, v in body_attrs.items())
        body = f'<body {attrs} xmlns="{NS_BOSH}">{payload_xml}</body>'
        resp = requests.post(
            self.bosh_url,
            data=body.encode("utf-8"),
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "Connection": "close",
            },
            timeout=self.timeout,
            verify=self.verify_ssl,
        )
        resp.raise_for_status()
        return resp.text

    def _next_rid(self) -> int:
        self.rid += 1
        return self.rid

    def login(self, localpart: str, password: str) -> None:
        # 1. BOSH session init
        init_attrs = {
            "rid": str(self.rid),
            "to": self.domain,
            "wait": str(self.wait),
            "hold": "1",
            "ver": "1.6",
            "xmpp:version": "1.0",
            "xmlns:xmpp": NS_XBOSH,
            "xml:lang": "en",
        }
        out = self._post(init_attrs)
        root = ET.fromstring(out)
        self.sid = root.attrib.get("sid")
        if not self.sid:
            raise BoshError(f"BOSH init returned no sid: {out!r}")

        # 2. SASL PLAIN
        auth_b64 = base64.b64encode(
            f"\x00{localpart}\x00{password}".encode("utf-8")
        ).decode("ascii")
        auth_xml = f'<auth xmlns="{NS_SASL}" mechanism="PLAIN">{auth_b64}</auth>'
        out = self._post({"rid": str(self._next_rid()), "sid": self.sid}, auth_xml)
        if "<success" not in out:
            raise BoshError(f"SASL PLAIN failed for {localpart}@{self.domain}")

        # 3. Stream restart
        self._post(
            {
                "rid": str(self._next_rid()),
                "sid": self.sid,
                "to": self.domain,
                "xml:lang": "en",
                "xmpp:restart": "true",
                "xmlns:xmpp": NS_XBOSH,
            }
        )

        # 4. Resource bind
        bind_xml = (
            '<iq type="set" id="bind_1" xmlns="jabber:client">'
            f'<bind xmlns="{NS_BIND}"/>'
            "</iq>"
        )
        out = self._post({"rid": str(self._next_rid()), "sid": self.sid}, bind_xml)
        try:
            root = ET.fromstring(out)
            jid_elem = root.find(f".//{{{NS_BIND}}}jid")
            if jid_elem is None or not (jid_elem.text or "").strip():
                raise BoshError("resource bind missing jid")
            self.full_jid = jid_elem.text.strip()
        except ET.ParseError as e:
            raise BoshError(f"bind response unparseable: {e}")

        # 5. Open session (XEP-0206 doesn't require, Prosody is OK without)
        sess_xml = (
            '<iq type="set" id="sess_1" xmlns="jabber:client">'
            '<session xmlns="urn:ietf:params:xml:ns:xmpp-session"/>'
            "</iq>"
        )
        self._post({"rid": str(self._next_rid()), "sid": self.sid}, sess_xml)

    def join(self, room_jid: str, nick: str) -> None:
        if not self.sid:
            raise BoshError("join before login")
        presence = (
            f'<presence xmlns="{NS_CLIENT}" to="{room_jid}/{_xml_escape(nick)}">'
            f'<x xmlns="{NS_MUC}"/>'
            "</presence>"
        )
        self._post({"rid": str(self._next_rid()), "sid": self.sid}, presence)
        # Settle so Prosody processes the join + history backfill before sends
        time.sleep(0.6)

    def send_groupchat(self, room_jid: str, body: str) -> None:
        if not self.sid:
            raise BoshError("send before login")
        msg = (
            f'<message xmlns="{NS_CLIENT}" to="{room_jid}" type="groupchat" '
            f'id="hyd-{int(time.time()*1000)}-{self.rid}">'
            f"<body>{_xml_escape(body)}</body>"
            "</message>"
        )
        self._post({"rid": str(self._next_rid()), "sid": self.sid}, msg)
        time.sleep(0.2)

    def leave(self, room_jid: str, nick: str) -> None:
        if not self.sid:
            return
        presence = (
            f'<presence xmlns="{NS_CLIENT}" to="{room_jid}/{_xml_escape(nick)}" '
            'type="unavailable"/>'
        )
        self._post({"rid": str(self._next_rid()), "sid": self.sid}, presence)

    def disconnect(self) -> None:
        if not self.sid:
            return
        try:
            self._post(
                {"rid": str(self._next_rid()), "sid": self.sid, "type": "terminate"}
            )
        finally:
            self.sid = None
            self.full_jid = None
