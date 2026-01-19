#!/usr/bin/env python3
"""
Seed initial XMPP messages for the Conversations app.
Creates realistic chat history between users for testing.

Chats seeded:
1. Short chat: agentuser <-> admin
2. Longer chat: agentuser <-> user1
3. Group chat: agentuser, user1, user2 in a MUC room
"""
import argparse
import base64
import json
import os
import random
import sys
import time
import xml.etree.ElementTree as ET

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BOSH_URL = "https://localhost:5281/http-bind"
DOMAIN = "10.0.2.2"
MUC_DOMAIN = "conference.10.0.2.2"

# Load credentials from secrets.json if available
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SECRETS_PATH = os.environ.get("SECRETS_PATH", os.path.join(SCRIPT_DIR, "secrets.json"))

try:
    with open(SECRETS_PATH) as f:
        secrets = json.load(f)
    ADMIN_PASSWORD = secrets["admin_password"]
    USER1_PASSWORD = secrets["user1_password"]
    USER2_PASSWORD = secrets["user2_password"]
except FileNotFoundError:
    # Fall back to environment variables (no hardcoded defaults)
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
    USER1_PASSWORD = os.environ.get("USER1_PASSWORD")
    USER2_PASSWORD = os.environ.get("USER2_PASSWORD")
    if not all([ADMIN_PASSWORD, USER1_PASSWORD, USER2_PASSWORD]):
        print(
            f"ERROR: secrets.json not found at {SECRETS_PATH} and "
            "ADMIN_PASSWORD/USER1_PASSWORD/USER2_PASSWORD environment variables not set",
            file=sys.stderr,
        )
        sys.exit(1)
except KeyError as e:
    print(f"ERROR: Missing key {e} in secrets.json", file=sys.stderr)
    sys.exit(1)

AGENTUSER_PASSWORD = "agentpass"


def create_bosh_body(rid, sid=None, **attrs):
    body_attrs = {"rid": str(rid), "xmlns": "http://jabber.org/protocol/httpbind"}
    if sid:
        body_attrs["sid"] = sid
    body_attrs.update(attrs)
    return ET.Element("body", body_attrs)


def send_bosh_request(url, body_elem, timeout=30):
    xml_bytes = ET.tostring(body_elem, encoding="utf-8")
    try:
        response = requests.post(
            url,
            data=xml_bytes,
            headers={"Content-Type": "text/xml; charset=utf-8"},
            timeout=timeout,
            verify=False,
        )
        return response.text
    except requests.exceptions.ReadTimeout:
        # BOSH long-polling timeout is expected for some requests
        return ""


class XMPPClient:
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.jid = f"{username}@{DOMAIN}"
        self.rid = random.randint(1000000, 9999999)
        self.sid = None
        self.resource = f"seed-{random.randint(1000, 9999)}"
        self.full_jid = None

    def connect(self):
        """Establish BOSH session and authenticate."""
        print(f"[{self.username}] Connecting...")

        # Initial session request
        body = create_bosh_body(
            rid=self.rid,
            to=DOMAIN,
            wait="60",
            hold="1",
            content="text/xml; charset=utf-8",
            ver="1.6",
        )
        body.set("xmpp:version", "1.0")
        body.set("xmlns:xmpp", "urn:xmpp:xmpp-bosh")
        response = send_bosh_request(BOSH_URL, body)

        if "sid=" not in response:
            print(f"[{self.username}] Failed to get session ID")
            return False
        self.sid = response.split("sid='")[1].split("'")[0]

        # Authenticate
        self.rid += 1
        auth_string = f"\x00{self.username}\x00{self.password}"
        auth_b64 = base64.b64encode(auth_string.encode()).decode()
        body = create_bosh_body(rid=self.rid, sid=self.sid)
        auth_elem = ET.SubElement(body, "auth")
        auth_elem.set("xmlns", "urn:ietf:params:xml:ns:xmpp-sasl")
        auth_elem.set("mechanism", "PLAIN")
        auth_elem.text = auth_b64
        response = send_bosh_request(BOSH_URL, body)

        if "success" not in response:
            print(f"[{self.username}] Authentication failed")
            return False

        # Restart stream
        self.rid += 1
        body = create_bosh_body(rid=self.rid, sid=self.sid, to=DOMAIN)
        body.set("xmpp:restart", "true")
        body.set("xmlns:xmpp", "urn:xmpp:xmpp-bosh")
        send_bosh_request(BOSH_URL, body)

        # Bind resource
        self.rid += 1
        body = create_bosh_body(rid=self.rid, sid=self.sid)
        iq = ET.SubElement(body, "iq")
        iq.set("type", "set")
        iq.set("id", "bind1")
        bind = ET.SubElement(iq, "bind")
        bind.set("xmlns", "urn:ietf:params:xml:ns:xmpp-bind")
        resource = ET.SubElement(bind, "resource")
        resource.text = self.resource
        response = send_bosh_request(BOSH_URL, body)
        self.full_jid = f"{self.jid}/{self.resource}"

        # Start session
        self.rid += 1
        body = create_bosh_body(rid=self.rid, sid=self.sid)
        iq = ET.SubElement(body, "iq")
        iq.set("type", "set")
        iq.set("id", "session1")
        session = ET.SubElement(iq, "session")
        session.set("xmlns", "urn:ietf:params:xml:ns:xmpp-session")
        send_bosh_request(BOSH_URL, body)

        # Send initial presence
        self.rid += 1
        body = create_bosh_body(rid=self.rid, sid=self.sid)
        ET.SubElement(body, "presence")
        send_bosh_request(BOSH_URL, body)

        print(f"[{self.username}] Connected")
        return True

    def send_message(self, to_jid, message_text):
        """Send a chat message to another user."""
        self.rid += 1
        message_id = f"msg-{int(time.time() * 1000)}-{random.randint(1000, 9999)}"

        body = create_bosh_body(rid=self.rid, sid=self.sid)
        message = ET.SubElement(body, "message")
        message.set("xmlns", "jabber:client")
        message.set("from", self.full_jid)
        message.set("to", to_jid)
        message.set("type", "chat")
        message.set("id", message_id)

        msg_body = ET.SubElement(message, "body")
        msg_body.text = message_text

        send_bosh_request(BOSH_URL, body, timeout=5)
        return True

    def join_muc(self, room_name, nickname=None):
        """Join a MUC room."""
        if nickname is None:
            nickname = self.username

        room_jid = f"{room_name}@{MUC_DOMAIN}"
        self.rid += 1

        body = create_bosh_body(rid=self.rid, sid=self.sid)
        presence = ET.SubElement(body, "presence")
        presence.set("from", self.full_jid)
        presence.set("to", f"{room_jid}/{nickname}")

        x = ET.SubElement(presence, "x")
        x.set("xmlns", "http://jabber.org/protocol/muc")

        send_bosh_request(BOSH_URL, body, timeout=5)
        print(f"[{self.username}] Joined room: {room_name}")
        return room_jid

    def send_muc_message(self, room_jid, message_text):
        """Send a message to a MUC room."""
        self.rid += 1
        message_id = f"muc-{int(time.time() * 1000)}-{random.randint(1000, 9999)}"

        body = create_bosh_body(rid=self.rid, sid=self.sid)
        message = ET.SubElement(body, "message")
        message.set("xmlns", "jabber:client")
        message.set("from", self.full_jid)
        message.set("to", room_jid)
        message.set("type", "groupchat")
        message.set("id", message_id)

        msg_body = ET.SubElement(message, "body")
        msg_body.text = message_text

        send_bosh_request(BOSH_URL, body, timeout=5)
        return True

    def disconnect(self):
        """Terminate the BOSH session."""
        self.rid += 1
        body = create_bosh_body(rid=self.rid, sid=self.sid, type="terminate")
        try:
            send_bosh_request(BOSH_URL, body, timeout=2)
        except Exception:
            pass
        print(f"[{self.username}] Disconnected")


def seed_admin_agent_chat():
    """Short chat between admin and agentuser."""
    print("\n=== Seeding: admin <-> agentuser (short chat) ===")

    admin = XMPPClient("admin", ADMIN_PASSWORD)
    agent = XMPPClient("agentuser", AGENTUSER_PASSWORD)

    try:
        if not admin.connect() or not agent.connect():
            print("Failed to connect users for admin-agent chat")
            return False

        messages = [
            ("admin", "agentuser@10.0.2.2", "Hey, welcome to the team!"),
            ("agentuser", "admin@10.0.2.2", "Thanks! Happy to be here."),
            ("admin", "agentuser@10.0.2.2", "Let me know if you need anything."),
        ]

        clients = {"admin": admin, "agentuser": agent}

        for sender, to_jid, msg in messages:
            clients[sender].send_message(to_jid, msg)
            time.sleep(0.3)

        print("Admin-Agent chat seeded successfully")
        return True
    finally:
        admin.disconnect()
        agent.disconnect()


def seed_agent_user1_chat():
    """Longer chat between agentuser and user1."""
    print("\n=== Seeding: agentuser <-> user1 (longer chat) ===")

    agent = XMPPClient("agentuser", AGENTUSER_PASSWORD)
    user1 = XMPPClient("user1", USER1_PASSWORD)

    try:
        if not agent.connect() or not user1.connect():
            print("Failed to connect users for agent-user1 chat")
            return False

        messages = [
            ("agentuser", "user1@10.0.2.2", "Hey! How's the project going?"),
            (
                "user1",
                "agentuser@10.0.2.2",
                "Pretty good! Almost done with the implementation.",
            ),
            ("agentuser", "user1@10.0.2.2", "Nice! What part are you working on now?"),
            (
                "user1",
                "agentuser@10.0.2.2",
                "The authentication module. It's a bit tricky.",
            ),
            ("agentuser", "user1@10.0.2.2", "I can help with that if you want."),
            (
                "user1",
                "agentuser@10.0.2.2",
                "That would be great! Can we pair on it tomorrow?",
            ),
            ("agentuser", "user1@10.0.2.2", "Sure, I'm free after 2pm."),
            ("user1", "agentuser@10.0.2.2", "Perfect, let's do 2:30 then."),
            (
                "agentuser",
                "user1@10.0.2.2",
                "Sounds good. I'll review the code beforehand.",
            ),
            ("user1", "agentuser@10.0.2.2", "Thanks! I'll send you the branch name."),
        ]

        clients = {"agentuser": agent, "user1": user1}

        for sender, to_jid, msg in messages:
            clients[sender].send_message(to_jid, msg)
            time.sleep(0.3)

        print("Agent-User1 chat seeded successfully")
        return True
    finally:
        agent.disconnect()
        user1.disconnect()


def seed_group_chat():
    """Group chat with agentuser, user1, and user2."""
    print("\n=== Seeding: Group chat (agentuser, user1, user2) ===")

    agent = XMPPClient("agentuser", AGENTUSER_PASSWORD)
    user1 = XMPPClient("user1", USER1_PASSWORD)
    user2 = XMPPClient("user2", USER2_PASSWORD)

    try:
        if not agent.connect() or not user1.connect() or not user2.connect():
            print("Failed to connect users for group chat")
            return False

        room_name = "project-team"

        # All users join the room
        room_jid = agent.join_muc(room_name)
        time.sleep(0.5)
        user1.join_muc(room_name)
        time.sleep(0.5)
        user2.join_muc(room_name)
        time.sleep(0.5)

        # Send group messages
        messages = [
            (agent, "Hey team! Quick sync on the project status?"),
            (user1, "Sure! I'm almost done with the backend."),
            (user2, "Frontend is coming along. Need the API docs though."),
            (agent, "I'll share the API docs in a bit."),
            (user1, "Great, that'll help us integrate faster."),
            (user2, "When's the deadline again?"),
            (agent, "End of next week. We're on track."),
            (user1, "Cool. Let's catch up again on Wednesday."),
            (user2, "Works for me!"),
            (agent, "Perfect. Talk then!"),
        ]

        for client, msg in messages:
            client.send_muc_message(room_jid, msg)
            time.sleep(0.3)

        print("Group chat seeded successfully")
        return True
    finally:
        agent.disconnect()
        user1.disconnect()
        user2.disconnect()


def trigger_conversations():
    """
    Send real-time messages to agentuser to trigger conversations appearing.
    This should be called AFTER agentuser is logged into the app.
    """
    print("\n=== Triggering conversations for agentuser ===")

    # Send a message from admin to agentuser
    admin = XMPPClient("admin", ADMIN_PASSWORD)
    if admin.connect():
        admin.send_message("agentuser@10.0.2.2", "Just checking in!")
        admin.disconnect()
        print("[trigger] Sent message from admin")
    else:
        print("[trigger] Failed to connect as admin")

    time.sleep(0.5)

    # Send a message from user1 to agentuser
    user1 = XMPPClient("user1", USER1_PASSWORD)
    if user1.connect():
        user1.send_message("agentuser@10.0.2.2", "Quick update on the project!")
        user1.disconnect()
        print("[trigger] Sent message from user1")
    else:
        print("[trigger] Failed to connect as user1")

    print("Trigger messages sent - conversations should now appear in app")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Seed XMPP messages for Conversations app"
    )
    parser.add_argument(
        "--trigger-only",
        action="store_true",
        help="Only send trigger messages (for after user login)",
    )
    args = parser.parse_args()

    print("=" * 60)
    if args.trigger_only:
        print("Sending trigger messages to agentuser")
    else:
        print("Seeding initial messages for Conversations app")
    print("=" * 60)
    print(f"BOSH URL: {BOSH_URL}")
    print(f"Domain: {DOMAIN}")

    if args.trigger_only:
        trigger_conversations()
        return 0

    success = True

    # Seed all conversations
    success = seed_admin_agent_chat() and success
    success = seed_agent_user1_chat() and success
    success = seed_group_chat() and success

    print("\n" + "=" * 60)
    if success:
        print("All messages seeded successfully!")
    else:
        print("Some messages failed to seed")
    print("=" * 60)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
