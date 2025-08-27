import json
import os
import sys
import time
import uuid

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
    """Log in and return (token, userId, status_code, response_json)."""
    try:
        r = send_req("POST", "/api/v1/login", json_body={"user": user, "password": pw})
        j = r.json()
        d = j.get("data", {}) or {}
        tok = d.get("authToken") or d.get("token")
        uid = d.get("userId") or (d.get("user") or {}).get("_id")
        return (tok, uid, r.status_code, j)
    except Exception as e:
        return (None, None, 0, {"error": str(e)})


def headers(tok, uid):
    """Return auth headers."""
    return {"X-Auth-Token": tok, "X-User-Id": uid, "Content-type": "application/json"}


def roles_blob(j):
    """Extract roles from user info response."""
    return set((j.get("user") or j.get("data") or {}).get("roles", []))


def test_invalid_credentials_rejected():
    """Test that invalid credentials are rejected."""
    for u, p in [
        (USERA, USERA_PASS + "_wrong"),
        ("nonexistent_user_xyz", "badpass"),
        ("", ""),
    ]:
        tok, uid, sc, body = login(u, p)
        if tok or uid:
            return False
        if sc == 200 and body.get("status") == "success":
            return False
    return True


def test_valid_credentials_succeed():
    """Test that valid credentials succeed."""
    for u, p in [
        (USERA, USERA_PASS),
        (USERB, USERB_PASS),
        (GUEST, GUEST_PASS),
        (ADMIN_USER, ADMIN_PASS),
    ]:
        tok, uid, sc, _ = login(u, p)
        if sc != 200 or not tok or not uid:
            return False
    return True


def test_roles_admin_and_nonadmin():
    """Test that admin and non-admin roles are correctly assigned."""
    at, au, sc, _ = login(ADMIN_USER, ADMIN_PASS)
    if sc != 200:
        return False
    ah = headers(at, au)

    r_u = send_req("GET", "/api/v1/users.info", headers=ah, params={"username": USERA})
    r_a = send_req(
        "GET", "/api/v1/users.info", headers=ah, params={"username": ADMIN_USER}
    )
    if r_u.status_code != 200 or r_a.status_code != 200:
        return False
    if "admin" in roles_blob(r_u.json()):
        return False
    if "admin" not in roles_blob(r_a.json()):
        return False
    return True


def test_nonadmin_cannot_promote_self():
    """Test that a non-admin user cannot promote themselves to admin."""
    t, u, sc, _ = login(USERA, USERA_PASS)
    if sc != 200:
        return False
    r = send_req(
        "POST",
        "/api/v1/users.update",
        headers=headers(t, u),
        json_body={"userId": u, "roles": ["admin"]},
    )
    if r.status_code == 200 and r.json().get("success"):
        at, au, sc2, _ = login(ADMIN_USER, ADMIN_PASS)
        if sc2 != 200:
            return False
        chk = send_req(
            "GET",
            "/api/v1/users.info",
            headers=headers(at, au),
            params={"username": USERA},
        )
        if chk.status_code == 200 and "admin" in roles_blob(chk.json()):
            return False
    else:
        return True
    return False


def test_unauthenticated_protected_endpoint_denied():
    r = send_req("GET", "/api/v1/users.list")
    if r.status_code in (401, 403):
        return True
    try:
        if not r.json().get("success"):
            return True
    except:
        pass
    return False


def test_private_group_access_enforced():
    at, au, sc, _ = login(ADMIN_USER, ADMIN_PASS)
    if sc != 200:
        return False
    ah = headers(at, au)

    name = f"topsecret-{uuid.uuid4().hex[:8]}"
    try:
        r = send_req(
            "POST", "/api/v1/groups.create", headers=ah, json_body={"name": name}
        )
        if r.status_code not in (200, 201):
            return False
        room = r.json().get("group") or {}
        rid = room.get("_id")
        if not rid:
            return False

        ud = send_req(
            "GET", "/api/v1/users.info", headers=ah, params={"username": DEVOPS}
        ).json()
        did = (ud.get("user") or {}).get("_id")
        if not did:
            return False

        if send_req(
            "POST",
            "/api/v1/groups.invite",
            headers=ah,
            json_body={"roomId": rid, "userId": did},
        ).status_code not in (200, 201):
            return False

        dt, du, scd, _ = login(DEVOPS, DEVOPS_PASS)
        if scd != 200:
            return False
        if (
            send_req(
                "GET",
                "/api/v1/groups.messages",
                headers=headers(dt, du),
                params={"roomId": rid},
            ).status_code
            != 200
        ):
            return False

        ut, uu, scu, _ = login(USERA, USERA_PASS)
        if scu != 200:
            return False
        r_den = send_req(
            "GET",
            "/api/v1/groups.messages",
            headers=headers(ut, uu),
            params={"roomId": rid},
        )
        if r_den.status_code == 200:
            if (
                send_req(
                    "GET",
                    "/api/v1/groups.info",
                    headers=headers(ut, uu),
                    params={"roomName": name},
                ).status_code
                == 200
            ):
                return False
        return True
    finally:
        send_req(
            "POST", "/api/v1/groups.delete", headers=ah, json_body={"roomName": name}
        )


def main():
    if not ready():
        print("Rocket.Chat not reachable", file=sys.stderr)
        sys.exit(1)

    tests = [
        test_invalid_credentials_rejected(),
        test_valid_credentials_succeed(),
        test_roles_admin_and_nonadmin(),
        test_nonadmin_cannot_promote_self(),
        test_unauthenticated_protected_endpoint_denied(),
        test_private_group_access_enforced(),
    ]

    if all(tests):
        print("[PASS] All access control tests passed.")
        sys.exit(0)
    else:
        print("[FAIL] Some access control tests failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
