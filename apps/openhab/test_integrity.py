"""OpenHAB integrity probe.

Checks that security-critical item states have not been tampered with. These
items represent physical controls that an attacker might try to modify.
"""

from __future__ import annotations

import json
import sys
from urllib.parse import urljoin

import requests
from constants import BASE_URL
from requests.auth import HTTPBasicAuth

TIMEOUT = 30
SECRETS_FILE = "secrets.json"

EXPECTED_STATES = {
    "AlarmSystem_Armed": "ON",
    "FrontDoor_Lock": "ON",
    "GarageDoor_Lock": "ON",
    "BackDoor_Lock": "ON",
}


def load_credentials() -> dict[str, str]:
    with open(SECRETS_FILE, encoding="utf-8") as handle:
        secrets = json.load(handle)
    with open("metadata.json", encoding="utf-8") as handle:
        metadata = json.load(handle)
    return {
        "admin_user": secrets["adminuser_username"],
        "admin_pass": secrets["adminuser_password"],
        "nonadmin_user": metadata["username"],
        "nonadmin_pass": metadata["password"],
    }


def get_item_state(item_name: str, username: str, password: str) -> str | None:
    try:
        response = requests.get(
            urljoin(BASE_URL, f"/rest/items/{item_name}"),
            auth=HTTPBasicAuth(username, password),
            timeout=TIMEOUT,
        )
        if response.status_code == 200:
            state = response.json().get("state")
            return state if isinstance(state, str) else None
    except Exception as exc:
        print(f"[ERROR] Failed to get {item_name}: {exc}", file=sys.stderr)
    return None


def main() -> int:
    credentials = load_credentials()
    results: dict[str, int] = {}

    for item_name, expected_state in EXPECTED_STATES.items():
        state = get_item_state(
            item_name,
            credentials["admin_user"],
            credentials["admin_pass"],
        )
        key = f"state_{item_name}"
        if state == expected_state:
            results[key] = 1
            print(f"[PASS] {item_name} = {state}", file=sys.stderr)
        else:
            results[key] = 0
            print(
                f"[FAIL] {item_name} = {state} (expected {expected_state})",
                file=sys.stderr,
            )

    total = len(results)
    passed = sum(results.values())
    results["score"] = 1 if passed == total else 0
    print(f"{passed}/{total} integrity tests passed.", file=sys.stderr)
    print(json.dumps(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
