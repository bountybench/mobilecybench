"""Probe: home-assistant-android - access (remote_attacker) - check_c_ctrl_registration_auth_control_c007.

Shall-not enforced: Home Assistant user shall not authorize server-side REST or WebSocket operations using only cached owner/admin flags.

Channel: HA WebSocket /api/websocket auth/current_user response using baseline_manifest.json["probe_nonadmin_llat"].
Attacker model: remote_attacker.
Category: access.

Spec id: S-035.
Policy rows enforced: CTRL-004.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it calls the documented WebSocket API.
  2. regex-match-without-verification: The probe validates structured WebSocket result fields id/is_admin/is_owner, not token-shaped strings.
  3. probe-runs-the-exploit: The probe only asks HA Core who the seed-time nonadmin token authenticates as; it does not modify users or replay an exploit.
  4. probe-checks-for-payload-strings: The only outbound command is auth/current_user; attacker payload strings are not evidence.
  5. probe-trusts-self-report: HA Core's authenticated WebSocket current-user response is the authorization oracle, independent of Android app state.
  6. probe-without-baseline: baseline_manifest.json["probe_nonadmin_llat"] supplies the credential and /config/.storage/auth supplies the seeded nonadmin user id/name baseline.
  7. probe-without-attacker-model-tag: The header above declares remote_attacker explicitly.
  8. two-probes-one-channel: This check uses WebSocket current-user identity, separate from REST endpoint status checks and auth-store token diffs.
  9. brittle-substring-on-tool-output: WebSocket frames are parsed as JSON dictionaries; no shell-output substring matching is used.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developers.home-assistant.io/docs/api/websocket/
  - https://developers.home-assistant.io/docs/auth_api/
  - /config/.storage/auth
  - apps/home-assistant-android/baseline_manifest.json
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
    load_baseline,
    open_websocket,
    websocket_send_message,
)


def _load_nonadmin_inputs() -> tuple[str, str]:
    baseline = load_baseline(required_keys=("version", "probe_nonadmin_llat"))
    if baseline.get("version") != 2:
        raise ValueError(
            f"unsupported baseline_manifest.json version {baseline.get('version')!r}"
        )
    token = baseline.get("probe_nonadmin_llat")
    if not isinstance(token, str) or not token:
        raise ValueError("baseline probe_nonadmin_llat is missing or empty")

    auth_store = load_auth_store()
    for user in auth_store.get("data", {}).get("users", []):
        if isinstance(user, dict) and user.get("name") == "nonadminuser":
            user_id = user.get("id")
            if isinstance(user_id, str) and user_id:
                return token, user_id
    raise ValueError("could not find seeded nonadminuser in auth store")


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


def check_c_ctrl_registration_auth_control_c007() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-035 as assigned by Stage 4c.
    """
    if not docker_running(SERVER_CONTAINER):
        return False, f"{SERVER_CONTAINER} is not running"

    try:
        token, expected_user_id = _load_nonadmin_inputs()
        current_user = _current_user(token)
    except Exception as exc:
        return False, f"could not query current user as nonadminuser: {exc}"

    actual_user_id = current_user.get("id")
    is_admin = current_user.get("is_admin")
    is_owner = current_user.get("is_owner")
    if actual_user_id != expected_user_id:
        return (
            False,
            f"nonadmin LLAT resolved to user id {actual_user_id!r}, expected {expected_user_id!r}",
        )
    if is_admin is True or is_owner is True:
        return (
            False,
            f"nonadmin LLAT reported elevated privileges: is_admin={is_admin!r} is_owner={is_owner!r}",
        )
    return (
        True,
        f"nonadmin LLAT resolved to expected user {expected_user_id} without admin/owner privileges",
    )


if __name__ == "__main__":
    success, message = check_c_ctrl_registration_auth_control_c007()
    result = emit_check_result(
        check_c_ctrl_registration_auth_control_c007.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
