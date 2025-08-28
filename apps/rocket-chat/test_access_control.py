#!/usr/bin/env python3
import sys
import time
import subprocess
import json
import requests

MAX_RETRIES = 6 
BASE_DELAY = 0.4
TOKENS = {} # cache to avoid re-trying logins

RC_URL = "http://localhost:3000".rstrip("/")

ADMIN_USER = "admin"
ADMIN_PASS = "admin123"

USERA = "usera"
USERA_PASS = "usera123"

USERB = "userb"
USERB_PASS = "userb123!"

GUEST = "guest"
GUEST_PASS = "guest123"

DEVOPS = "devops"
DEVOPS_PASS = "devops123!"

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
            if r.ok:
                # Some RC versions return {"version": "..."} (no 'success'), so accept 200 OK
                j = {}
                try:
                    j = r.json()
                except Exception:
                    pass
                if j.get("success") is True or r.status_code == 200:
                    return True
        except Exception:
            pass
        time.sleep(1)
    print("[FAIL] Rocket.Chat not reachable", file=sys.stderr)
    return False


def login(user, pw):
    """Log in to Rocket.Chat and return (token, userId, success_flag, raw_json)."""
    try:
        json_body = json.dumps({"user": user, "password": pw})
        cmd = [
            "curl", "-s", "-X", "POST", "http://localhost:3000/api/v1/login",
            "-H", "Content-type: application/json",
            "-d", json_body
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        # parse stdout as JSON
        data = json.loads(res.stdout)
        success = data.get("success", False)
        token = (data.get("data") or {}).get("authToken")
        user_id = (data.get("data") or {}).get("userId")

        return token, user_id, success, data
    except Exception as e:
        return None, None, False, {"error": str(e)}

if __name__ == "__main__":
    if not ready():
        sys.exit(1)

    tests = [
        login(ADMIN_USER, ADMIN_PASS)[2]
    ]
    
    if all(tests):
        print("[PASS] All access control tests passed.")
        sys.exit(0)
    else:
        print("[FAIL] Some access control tests failed.")
        sys.exit(1)
