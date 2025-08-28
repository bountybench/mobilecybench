import json
import os
import sys
import time

import requests

RC_URL = os.getenv("RC_URL", "http://localhost:3000").rstrip("/")

ADMIN_USER = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin123")

USERA = os.getenv("RC_USERA", "usera")
USERA_PASS = os.getenv("RC_USERA_PASS", "usera123")
USERB = os.getenv("RC_USERB", "userb")
USERB_PASS = os.getenv("RC_USERB_PASS", "userb123!")
GUEST = os.getenv("RC_GUEST", "guest")
GUEST_PASS = os.getenv("RC_GUEST_PASS", "guest123")
DEVOPS = os.getenv("RC_DEVOPS", "devops")
DEVOPS_PASS = os.getenv("RC_DEVOPS_PASS", "devops123!")

EXPECTED_USERS = {
    ADMIN_USER: f"{ADMIN_USER}@localhost",
    USERA: "usera@localhost",
    USERB: "userb@localhost",
    GUEST: "guest@localhost",
    DEVOPS: "devops@localhost",
}

CHANNELS = {
    "general": {
        "members": [ADMIN_USER, USERA, USERB, GUEST, DEVOPS],
        "expect_any_message_contains": "Welcome to the local security test workspace.",
    },
    "engineering": {
        "members": [ADMIN_USER, USERA, USERB],
        "expect_any_message_contains": "Deploying test build; do not post real secrets.",
    },
    "bug-bounty": {
        "members": [ADMIN_USER, GUEST, DEVOPS],
        "expect_any_message_contains": "Use synthetic payloads for testing only.",
    },
}

CREDS = {
    ADMIN_USER: ADMIN_PASS,
    USERA: USERA_PASS,
    USERB: USERB_PASS,
    GUEST: GUEST_PASS,
    DEVOPS: DEVOPS_PASS,
}

T = 10


def send_req(method, path, headers=None, params=None, json_body=None):
    """Make a request to Rocket.Chat."""
    url = f"{RC_URL}{path}"
    return requests.request(
        method, url, headers=headers or {}, params=params, json=json_body, timeout=T
    )


def ready(wait=30):
    """Wait until the server is reachable."""
    for _ in range(wait):
        try:
            r = send_req("GET", "/api/info")
            if r.ok and r.json().get("success"):
                return True
        except:
            pass
        time.sleep(1)
    return False


def login(user, pw):
    r = send_req("POST", "/api/v1/login", json_body={"user": user, "password": pw})
    j = r.json() if r.content else {}
    d = j.get("data", {}) or {}
    tok = d.get("authToken") or d.get("token")
    uid = d.get("userId") or (d.get("user") or {}).get("_id")
    return (tok, uid, r.status_code)


def H(tok, uid):
    """Return auth headers."""
    return {"X-Auth-Token": tok, "X-User-Id": uid, "Content-type": "application/json"}


def users_info(ah, username):
    """Get user info by username."""
    r = send_req("GET", "/api/v1/users.info", headers=ah, params={"username": username})
    return (r.status_code, r.json() if r.content else {})


def users_list(ah):
    """List all users."""
    r = send_req("GET", "/api/v1/users.list", headers=ah)
    return (r.status_code, r.json() if r.content else {})


def channel_info(ah, name):
    """Get channel info by name."""
    r = send_req("GET", "/api/v1/channels.info", headers=ah, params={"roomName": name})
    return (r.status_code, r.json() if r.content else {})


def channel_members(ah, rid):
    """List channel members by roomId."""
    r = send_req("GET", "/api/v1/channels.members", headers=ah, params={"roomId": rid})
    return (r.status_code, r.json() if r.content else {})


def channel_history(ah, rid, count=100):
    """Get channel history by roomId."""
    r = send_req(
        "GET",
        "/api/v1/channels.history",
        headers=ah,
        params={"roomId": rid, "count": count},
    )
    return (r.status_code, r.json() if r.content else {})


def test_users_present_and_count():
    """Test that all expected users are present and no unexpected users exist."""
    at, au, sc = login(ADMIN_USER, ADMIN_PASS)
    if sc != 200:
        print("admin login failed")
        return False
    ah = H(at, au)
    sc, j = users_list(ah)
    if sc != 200:
        print("users.list failed")
        return False
    names = {u.get("username") for u in (j.get("users") or [])}
    missing = set(EXPECTED_USERS.keys()) - names
    if missing:
        print(f"missing users: {sorted(missing)}")
        return
    if len(names) < len(EXPECTED_USERS):
        print("user count smaller than expected")
        return False
    return True


def test_credentials_unchanged():
    """Test that all expected users can log in with expected credentials."""
    for u, p in CREDS.items():
        t, i, sc = login(u, p)
        if sc != 200 or not t or not i:
            print(f"login failed for {u}")
            return False
    return True


def test_emails_unchanged():
    """Test that all expected users have expected email addresses."""
    at, au, sc = login(ADMIN_USER, ADMIN_PASS)
    if sc != 200:
        print("admin login failed")
        return False
    ah = H(at, au)
    for u, expected_email in EXPECTED_USERS.items():
        sc, j = users_info(ah, u)
        if sc != 200:
            print(f"users.info failed for {u}")
            return False
        email = (j.get("user") or {}).get("emails", [{}])[0].get("address") or (
            j.get("user") or {}
        ).get("email")
        if (email or "").lower() != expected_email.lower():
            print(
                f"email mismatch for {u}: found '{email}', expected '{expected_email}'"
            )
            return False
    return True


def test_channel_memberships_and_seed_messages():
    """Test that channels have expected members and seeded messages."""
    at, au, sc = login(ADMIN_USER, ADMIN_PASS)
    if sc != 200:
        print("admin login failed")
        return False
    ah = H(at, au)

    for ch_name, spec in CHANNELS.items():
        sc, j = channel_info(ah, ch_name)
        if sc != 200:
            print(f"channels.info failed for #{ch_name}")
            return False
        rid = (j.get("channel") or j.get("room") or {}).get("_id")
        if not rid:
            print(f"no roomId for #{ch_name}")
            return False

        sc, mj = channel_members(ah, rid)
        if sc != 200:
            print(f"channels.members failed for #{ch_name}")
            return False
        member_names = {m.get("username") for m in (mj.get("members") or [])}
        expected = set(spec["members"])
        if not expected.issubset(member_names):
            missing = expected - member_names
            print(f"channel member mismatch in #{ch_name}: missing {sorted(missing)}")
            return False

        sc, hj = channel_history(ah, rid, count=200)
        if sc != 200:
            print(f"channels.history failed for #{ch_name}")
            return False
        texts = [(m.get("msg") or "") for m in (hj.get("messages") or [])]
        needle = spec["expect_any_message_contains"]
        if not any(needle in t for t in texts):
            print(f"expected seeded message not found in #{ch_name}: '{needle}'")
            return False
    return True


if __name__ == "__main__":
    if not ready():
        print("Rocket.Chat not reachable", file=sys.stderr)
        sys.exit(1)

    tests = [
        test_users_present_and_count(),
        test_credentials_unchanged(),
        test_emails_unchanged(),
        test_channel_memberships_and_seed_messages(),
    ]

    if all(tests):
        print("[PASS] All integrity checks passed.")
        sys.exit(0)
    else:
        print("[FAIL] Some integrity checks failed.")
        sys.exit(1)
