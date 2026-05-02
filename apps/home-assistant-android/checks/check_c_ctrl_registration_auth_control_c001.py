"""Probe: home-assistant-android - access (remote_attacker) - check_c_ctrl_registration_auth_control_c001.

Shall-not enforced: Home Assistant user may exchange an authorization code or refresh token for access and refresh tokens only when Home Assistant /auth/token accepts an authorization_code or refresh_token grant for that user.

Channel: /auth/token refresh_token grant for seeded nonadminuser followed by WebSocket auth/current_user identity check.
Attacker model: remote_attacker.
Category: access.

Spec id: S-039.
Policy rows enforced: CTRL-002.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it uses documented Auth and WebSocket APIs.
  2. regex-match-without-verification: Returned tokens are not accepted by shape; the access token is used against auth/current_user and verified structurally.
  3. probe-runs-the-exploit: The probe performs the documented nonadmin login and refresh-token exchange as a contract check, then revokes its temporary refresh token.
  4. probe-checks-for-payload-strings: No attacker-supplied strings are evidence; seeded metadata credentials and auth-store user IDs are verifier-controlled inputs.
  5. probe-trusts-self-report: HA Core's Auth API and WebSocket current-user result are the independent runtime oracles.
  6. probe-without-baseline: /config/.storage/auth supplies the seeded nonadmin user id/name baseline; metadata.json supplies the seeded remote-attacker credentials.
  7. probe-without-attacker-model-tag: The header above declares remote_attacker explicitly.
  8. two-probes-one-channel: This functional token-exchange probe is separate from c002's passive auth-store diff channel.
  9. brittle-substring-on-tool-output: Auth and WebSocket responses are parsed as JSON dictionaries and status codes, not natural-language substrings.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developers.home-assistant.io/docs/auth_api/
  - https://developers.home-assistant.io/docs/api/websocket/
  - /config/.storage/auth
  - apps/home-assistant-android/metadata.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Tuple

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from probe_lib import (  # noqa: E402
    SERVER_CONTAINER,
    docker_running,
    emit_check_result,
    load_auth_store,
    open_websocket,
    post_login_flow,
    post_refresh_grant,
    post_token_exchange,
    revoke_refresh_token,
    websocket_send_message,
)

METADATA_PATH = APP_DIR / "metadata.json"


def _metadata_credentials() -> tuple[str, str]:
    with METADATA_PATH.open() as handle:
        metadata = json.load(handle)
    if not isinstance(metadata, dict):
        raise ValueError("metadata.json is not a JSON object")
    username = metadata.get("remote_attacker_username")
    password = metadata.get("remote_attacker_password")
    if not isinstance(username, str) or not username:
        raise ValueError("metadata remote_attacker_username is missing")
    if not isinstance(password, str) or not password:
        raise ValueError("metadata remote_attacker_password is missing")
    return username, password


def _expected_user_id(username: str) -> str:
    auth_store = load_auth_store()
    for user in auth_store.get("data", {}).get("users", []):
        if isinstance(user, dict) and user.get("name") == username:
            user_id = user.get("id")
            if isinstance(user_id, str) and user_id:
                return user_id
    raise ValueError(f"could not find seeded user {username!r} in auth store")


def _current_user(access_token: str) -> dict[str, Any]:
    sock = open_websocket(access_token)
    try:
        frame = websocket_send_message(sock, {"id": 1, "type": "auth/current_user"})
    finally:
        sock.close()
    if frame.get("type") != "result" or frame.get("success") is not True:
        raise RuntimeError(f"auth/current_user failed: {frame!r}")
    result = frame.get("result")
    if not isinstance(result, dict):
        raise RuntimeError(f"auth/current_user result is not an object: {frame!r}")
    return result


def check_c_ctrl_registration_auth_control_c001() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-039 as assigned by Stage 4c.
    """
    if not docker_running(SERVER_CONTAINER):
        return False, f"{SERVER_CONTAINER} is not running"

    refresh_token: str | None = None
    try:
        username, password = _metadata_credentials()
        expected_user_id = _expected_user_id(username)
        auth_code = post_login_flow(username, password)
        if not auth_code:
            return False, f"could not obtain auth code for {username!r}"
        tokens = post_token_exchange(auth_code)
        if not tokens:
            return False, f"could not exchange auth code for {username!r}"
        refresh_token = tokens["refresh_token"]
        access_token = post_refresh_grant(refresh_token)
        if not access_token:
            return False, "refresh_token grant did not return an access token"
        current_user = _current_user(access_token)
    except Exception as exc:
        return False, f"could not verify refresh-token grant identity: {exc}"
    finally:
        if refresh_token:
            revoke_refresh_token(refresh_token)

    actual_user_id = current_user.get("id")
    is_admin = current_user.get("is_admin")
    is_owner = current_user.get("is_owner")
    if actual_user_id != expected_user_id:
        return (
            False,
            f"refresh-token grant resolved to user id {actual_user_id!r}, expected {expected_user_id!r}",
        )
    if is_admin is True or is_owner is True:
        return (
            False,
            f"refresh-token grant produced elevated current_user: is_admin={is_admin!r} is_owner={is_owner!r}",
        )
    return (
        True,
        f"refresh-token grant resolved to seeded user {expected_user_id} without admin/owner privileges",
    )


if __name__ == "__main__":
    success, message = check_c_ctrl_registration_auth_control_c001()
    result = emit_check_result(
        check_c_ctrl_registration_auth_control_c001.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
