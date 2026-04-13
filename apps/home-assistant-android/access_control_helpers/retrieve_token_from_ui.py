import argparse
import sys

import requests

from .get_llat_from_token import login_with_llat

CLIENT_ID = "https://home-assistant.io/android"


def parse_args():
    parser = argparse.ArgumentParser(description="Home Assistant login helper")
    parser.add_argument("--username", required=True, help="username")
    parser.add_argument("--password", required=True, help="password")
    parser.add_argument(
        "--hostname", required=True, help="Host address where HA is running"
    )
    return parser.parse_args()


def retrieve_access_token(hostname: str, username: str, password: str) -> str | None:
    """Authenticate through HA's login-flow API and return a short-lived token."""
    base_url = f"https://{hostname}:8123"

    try:
        response = requests.post(
            f"{base_url}/auth/login_flow",
            json={
                "client_id": CLIENT_ID,
                "handler": ["homeassistant", None],
                "redirect_uri": CLIENT_ID,
            },
            timeout=10,
            verify=False,
        )
        response.raise_for_status()
        flow_id = response.json()["flow_id"]

        response = requests.post(
            f"{base_url}/auth/login_flow/{flow_id}",
            json={
                "username": username,
                "password": password,
                "client_id": CLIENT_ID,
            },
            timeout=10,
            verify=False,
        )
        response.raise_for_status()
        result = response.json()

        if result.get("type") != "create_entry":
            return None

        response = requests.post(
            f"{base_url}/auth/token",
            data={
                "grant_type": "authorization_code",
                "code": result["result"],
                "client_id": CLIENT_ID,
            },
            timeout=10,
            verify=False,
        )
        response.raise_for_status()
        return response.json().get("access_token")
    except Exception as exc:
        print(f"Error retrieving access token: {exc}", file=sys.stderr)
        return None


def retrieve_llat(hostname: str, username: str, password: str) -> str | None:
    """Return a Home Assistant long-lived access token for the seeded user."""
    access_token = retrieve_access_token(hostname, username, password)
    if not access_token:
        return None
    return login_with_llat(hostname, access_token)


if __name__ == "__main__":
    args = parse_args()
    access_token = retrieve_access_token(args.hostname, args.username, args.password)

    if not access_token:
        print("Failed to obtain access token")
        sys.exit(1)

    print(f"\nAccess token: {access_token}")
    print("Now retrieving LLAT via WebSocket...")
    llat = login_with_llat(args.hostname, access_token)
    if llat:
        print(f"LLAT created successfully: {llat}")
    else:
        print("Failed to create LLAT")
        sys.exit(1)
