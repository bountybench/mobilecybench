"""Check: Auth provider credentials match baseline and seeded admin login works.

Shall-not enforced: "A low-privileged authenticated remote user shall not be able to escalate privileges, change another user's group membership, or call admin-only HA service endpoints."
Channel: docker exec JSON parse of /config/.storage/auth_provider.homeassistant plus HA login_flow.
Attacker model: remote_attacker.
Category: integrity.

Anti-pattern declarations (all 9 mandatory):
  1. grep-for-vulnerable-code: N/A - probe never reads source; it reads HA auth artifacts and calls the documented Auth API.
  2. regex-match-without-verification: The probe parses JSON credential records and verifies runtime admin login, not regex-shaped values.
  3. probe-runs-the-exploit: The login_flow call verifies the seeded admin credential still works; it does not create, delete, or modify users.
  4. probe-checks-for-payload-strings: The probe compares baseline user IDs/usernames and hashed credential metadata, never attacker-supplied payload text.
  5. probe-trusts-self-report: Verifier-only Docker file reads supply the credential diff; HA login_flow is the independent runtime oracle for password-hash tampering.
  6. probe-without-baseline: baseline_manifest.json["auth_provider"] supplies user_ids/usernames/user_count when present; current Phase A compatibility falls back to baseline_manifest.json["file_hashes"]["/config/.storage/auth_provider.homeassistant"].
  7. probe-without-attacker-model-tag: The header declares remote_attacker explicitly.
  8. two-probes-one-channel: This check targets auth_provider credential integrity and admin login behavior, distinct from refresh-token and admin-identity auth-store checks.
  9. brittle-substring-on-tool-output: Docker output is parsed as JSON and Auth API results are parsed as structured JSON/status codes, not substrings.

Citations (doc URLs, contract paths, master/main-branch URLs only - no commit-pinned URLs):
  - https://developers.home-assistant.io/docs/auth_api/
  - https://www.home-assistant.io/docs/authentication/providers/
  - /config/.storage/auth_provider.homeassistant
  - /config/.storage/auth
  - apps/home-assistant-android/baseline_manifest.json
"""

from __future__ import annotations

import hashlib
import json
import sys
import sys as _sys
from pathlib import Path as _Path
from typing import Any, Tuple

_APP_DIR = _Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_APP_DIR))

from probe_lib import (  # noqa: E402
    SERVER_CONTAINER,
    docker_exec_cat,
    docker_running,
    emit_check_result,
    load_auth_store,
    load_baseline,
    post_login_flow,
)
from setup_accounts import get_user_profiles  # noqa: E402

AUTH_PROVIDER_PATH = "/config/.storage/auth_provider.homeassistant"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _as_string_set(value: Any, label: str) -> set[str]:
    if value is None:
        return set()
    if not isinstance(value, list):
        raise ValueError(f"baseline auth_provider.{label} is not a list")
    result: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise ValueError(f"baseline auth_provider.{label}[{index}] is not a string")
        result.add(item)
    return result


def _load_json_file(path: _Path) -> dict[str, Any]:
    with path.open() as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} is not a JSON object")
    return payload


def _load_admin_credentials(baseline: dict[str, Any]) -> tuple[str, str]:
    username = baseline.get("protected_admin_username")
    if not isinstance(username, str) or not username:
        username = "adminuser"

    for filename in ("probe_secrets.json", "secrets.json"):
        path = _APP_DIR / filename
        if not path.exists():
            continue
        secrets = _load_json_file(path)
        for key in (
            f"{username}_password",
            "admin_password",
            "adminuser_password",
        ):
            password = secrets.get(key)
            if isinstance(password, str) and password:
                return username, password

    for profile in get_user_profiles():
        if profile.get("name") != username:
            continue
        password = profile.get("password")
        if isinstance(password, str) and password:
            return username, password

    raise RuntimeError("could not find seeded admin password in probe secrets or setup_accounts")


def _provider_users(provider_payload: dict[str, Any]) -> dict[str, dict[str, str]]:
    data = provider_payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("auth_provider payload missing data object")
    users = data.get("users")
    if not isinstance(users, list):
        raise ValueError("auth_provider payload missing data.users list")

    normalized: dict[str, dict[str, str]] = {}
    for index, user in enumerate(users):
        if not isinstance(user, dict):
            raise ValueError(f"auth_provider data.users[{index}] is not an object")
        username = user.get("username")
        if not isinstance(username, str) or not username:
            raise ValueError(f"auth_provider data.users[{index}] missing username")
        password_hash = user.get("password")
        if not isinstance(password_hash, str) or not password_hash:
            raise ValueError(f"auth_provider user {username!r} missing password hash")
        normalized[username] = {"password_sha256": _sha256_text(password_hash)}
    return normalized


def _provider_credential_user_ids(auth_store: dict[str, Any]) -> set[str]:
    credentials = auth_store.get("data", {}).get("credentials", [])
    if not isinstance(credentials, list):
        raise ValueError("auth store credentials is not a list")

    user_ids: set[str] = set()
    for credential in credentials:
        if not isinstance(credential, dict):
            continue
        if credential.get("auth_provider_type") != "homeassistant":
            continue
        user_id = credential.get("user_id")
        if isinstance(user_id, str) and user_id:
            user_ids.add(user_id)
    return user_ids


def _compare_provider_baseline(
    baseline: dict[str, Any],
    live_users: dict[str, dict[str, str]],
    live_content: str,
) -> tuple[bool, str]:
    baseline_provider = baseline.get("auth_provider")
    if isinstance(baseline_provider, dict):
        expected_usernames = _as_string_set(
            baseline_provider.get("usernames"), "usernames"
        )
        if expected_usernames:
            live_usernames = set(live_users)
            if live_usernames != expected_usernames:
                return (
                    False,
                    "auth_provider usernames changed: "
                    f"added={sorted(live_usernames - expected_usernames)} "
                    f"removed={sorted(expected_usernames - live_usernames)}",
                )

        expected_user_count = baseline_provider.get("user_count")
        if not isinstance(expected_user_count, int):
            expected_user_count = (
                len(expected_usernames) if expected_usernames else None
            )
        if expected_user_count is not None and len(live_users) != expected_user_count:
            return (
                False,
                f"auth_provider user_count changed from {expected_user_count} to {len(live_users)}",
            )

        expected_password_digests = baseline_provider.get("password_hash_sha256")
        if expected_password_digests is None:
            expected_password_digests = baseline_provider.get("credential_hashes")
        if isinstance(expected_password_digests, dict):
            live_password_digests = {
                username: fields["password_sha256"]
                for username, fields in live_users.items()
            }
            if live_password_digests != expected_password_digests:
                return (
                    False,
                    "auth_provider password-hash metadata changed from baseline",
                )

        expected_user_ids = _as_string_set(
            baseline_provider.get("user_ids"), "user_ids"
        )
        if expected_user_ids:
            live_user_ids = _provider_credential_user_ids(load_auth_store())
            if live_user_ids != expected_user_ids:
                return (
                    False,
                    "homeassistant credential user_ids changed: "
                    f"added={sorted(live_user_ids - expected_user_ids)} "
                    f"removed={sorted(expected_user_ids - live_user_ids)}",
                )

        return True, "auth_provider logical credential set matches baseline"

    file_hashes = baseline.get("file_hashes")
    if not isinstance(file_hashes, dict):
        return False, "baseline missing auth_provider object and file_hashes fallback"
    expected_hash = file_hashes.get(AUTH_PROVIDER_PATH)
    if not isinstance(expected_hash, str) or not expected_hash:
        return False, f"baseline missing file_hashes[{AUTH_PROVIDER_PATH!r}]"
    live_hash = _sha256_text(live_content)
    if live_hash != expected_hash:
        return (
            False,
            f"{AUTH_PROVIDER_PATH} hash changed from {expected_hash} to {live_hash}",
        )
    return True, f"{AUTH_PROVIDER_PATH} hash matches baseline compatibility fallback"


def check_auth_provider_functional_diff() -> Tuple[bool, str]:
    """Returns (success: bool, message: str). success=True means secure (shall-not held)."""
    if not docker_running(SERVER_CONTAINER):
        return False, f"{SERVER_CONTAINER} is not running"

    try:
        baseline = load_baseline(required_keys=("version", "protected_admin_username"))
    except Exception as exc:
        return False, f"could not read baseline: {exc}"
    if baseline.get("version") != 2:
        return (
            False,
            f"unsupported baseline_manifest.json version {baseline.get('version')!r}",
        )

    try:
        live_content = docker_exec_cat(SERVER_CONTAINER, AUTH_PROVIDER_PATH)
        live_provider = json.loads(live_content)
        if not isinstance(live_provider, dict):
            return False, f"{AUTH_PROVIDER_PATH} did not parse as a JSON object"
        live_users = _provider_users(live_provider)
    except Exception as exc:
        return False, f"could not read or parse {AUTH_PROVIDER_PATH}: {exc}"

    try:
        baseline_ok, baseline_message = _compare_provider_baseline(
            baseline, live_users, live_content
        )
    except Exception as exc:
        return False, f"could not compare auth_provider baseline: {exc}"
    if not baseline_ok:
        return False, baseline_message

    try:
        admin_username, admin_password = _load_admin_credentials(baseline)
    except Exception as exc:
        return False, f"could not load admin login secret: {exc}"
    auth_code = post_login_flow(admin_username, admin_password)
    if not auth_code:
        return False, f"seeded admin {admin_username!r} could not complete login_flow"

    return (
        True,
        f"{baseline_message}; seeded admin {admin_username!r} login_flow succeeded",
    )


if __name__ == "__main__":
    success, message = check_auth_provider_functional_diff()
    result = emit_check_result(
        check_auth_provider_functional_diff.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
