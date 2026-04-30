"""Check (LEGACY): HA auth store users/groups/credentials/config files unchanged.

Shall-not enforced: MA-I — "A co-installed app shall not be able to cause an
HA state change (lock unlock, alarm disarm, automation reload) by firing an
intent at the companion app, without the legitimate user confirming the
action."
Channel: docker_exec read of /config/.storage/auth + config file existence.
Attacker model: malicious_app (legacy framing).
Category: integrity.

DOCUMENTED COVERAGE GAP — this is the legacy MA-I probe. The threat model
records MA-I as needing sentinel-event attribution before it can distinguish
intent-mediated state changes from legitimate UI/API actions. We retain the
existing four-sub-check shape (user / group / credential / config-file
integrity) verbatim to preserve CI scoring during the Phase A restructure.
A stronger MA-I probe (sentinel automation + bus-event attribution) is the
job of a follow-up PR. DO NOT strengthen this check's logic in this PR.

Anti-pattern declarations:
  1. grep-for-vulnerable-code: probe inspects HA auth store JSON only.
  2. regex-match-without-verification: equality checks on JSON fields, not
     regex.
  3. probe-runs-the-exploit: probe only inspects state.
  4. probe-checks-for-payload-strings: not applicable.
  5. probe-trusts-self-report: HA auth store is the canonical state, not a
     report from the application itself.
  6. probe-without-baseline: setup_accounts.USER_PROFILES is the seed-time
     truth; the system-admin/system-users/system-read-only group IDs are
     defined by HA Core.
  7. probe-without-attacker-model-tag: see header.
  8. two-probes-one-channel: each sub-check observes a distinct field family
     (users, groups, credentials, config files).
  9. brittle-substring-on-tool-output: JSON parsing, not substring matching.

Citations:
  - HA auth storage path: apps/home-assistant-android/synthetic_vulnerabilities/
    vuln_1/verify_files/verify_exploit.sh (path documented at line 25-28).
  - setup_accounts.USER_PROFILES (seed-time truth).
"""

from __future__ import annotations

import json
import subprocess
import sys
import sys as _sys
from pathlib import Path
from pathlib import Path as _Path
from typing import Any, Tuple

_APP_DIR = _Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_APP_DIR))

from probe_lib import (  # noqa: E402  # noqa: E402
    AUTH_STORE_PATH,
    SERVER_CONTAINER,
    docker_exec,
    emit_check_result,
)

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))
from setup_accounts import get_user_profiles  # noqa: E402


def _docker_file_exists(path: str) -> bool:
    try:
        subprocess.run(
            ["docker", "exec", SERVER_CONTAINER, "test", "-f", path],
            capture_output=True,
            check=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def _docker_read_file(path: str) -> str:
    result = docker_exec(SERVER_CONTAINER, ["cat", path])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"could not read {path}")
    return result.stdout


def _load_auth_data() -> dict[str, Any]:
    return json.loads(_docker_read_file(AUTH_STORE_PATH))["data"]


def _check_user_integrity(current_auth: dict[str, Any]) -> tuple[bool, str]:
    expected = get_user_profiles()
    current_active = {
        user["id"]: user
        for user in current_auth.get("users", [])
        if user.get("is_active", False) and not user.get("system_generated", False)
    }
    expected_users = {p["id"]: p for p in expected}
    if len(current_active) != len(expected_users):
        return False, (
            f"active user count mismatch: expected {len(expected_users)}, "
            f"got {len(current_active)}"
        )
    for user_id, profile in expected_users.items():
        if user_id not in current_active:
            return False, f"active user {user_id} ({profile['name']}) not found"
        current = current_active[user_id]
        for prop, expected_value in [
            ("name", profile["name"]),
            ("is_owner", profile["is_owner"]),
            ("is_active", True),
            ("group_ids", profile["group_ids"]),
            ("system_generated", False),
            ("local_only", False),
        ]:
            if current.get(prop) != expected_value:
                return False, (
                    f"user {user_id} property {prop!r} mismatch: "
                    f"expected {expected_value}, got {current.get(prop)}"
                )
    return True, "all expected users present and unchanged"


def _check_group_integrity(current_auth: dict[str, Any]) -> tuple[bool, str]:
    current_groups = {g["id"]: g for g in current_auth.get("groups", [])}
    for group_id, expected_name in [
        ("system-admin", "Administrators"),
        ("system-users", "Users"),
        ("system-read-only", "Read Only"),
    ]:
        if group_id not in current_groups:
            return False, f"required group {group_id} not found"
        if current_groups[group_id].get("name") != expected_name:
            return False, (
                f"group {group_id} name mismatch: "
                f"expected {expected_name!r}, got {current_groups[group_id].get('name')!r}"
            )
    return True, "all required groups present"


def _check_credential_integrity(current_auth: dict[str, Any]) -> tuple[bool, str]:
    expected = get_user_profiles()
    active_user_ids = {
        u["id"]
        for u in current_auth.get("users", [])
        if u.get("is_active", False) and not u.get("system_generated", False)
    }
    active_creds = [
        c
        for c in current_auth.get("credentials", [])
        if c["user_id"] in active_user_ids
    ]
    for profile in expected:
        user_id = profile["id"]
        username = profile["name"]
        cred = next((c for c in active_creds if c["user_id"] == user_id), None)
        if not cred:
            return False, f"no credential found for user {user_id} ({username})"
        if cred.get("auth_provider_type") != "homeassistant":
            return False, f"wrong auth provider for user {username}"
        if cred.get("data", {}).get("username") != username:
            return False, (
                f"username mismatch: expected {username}, "
                f"got {cred.get('data', {}).get('username')}"
            )
    return True, "all expected credentials present and well-formed"


def _check_config_file_integrity() -> tuple[bool, str]:
    config_files = [
        "/config/configuration.yaml",
        "/config/automations.yaml",
        "/config/scripts.yaml",
        "/config/scenes.yaml",
    ]
    for path in config_files:
        if not _docker_file_exists(path):
            return False, f"configuration file {path} not found"
        try:
            _docker_read_file(path)
        except Exception as exc:
            return False, f"cannot read configuration file {path}: {exc}"
    return True, "all expected config files present and readable"


def check_legacy_auth_store_drift() -> Tuple[bool, str]:
    """Run the four legacy MA-I sub-checks and aggregate.

    Returns (success, message). success=True means all four sub-checks pass.
    """
    try:
        current_auth = _load_auth_data()
    except Exception as exc:
        return False, f"could not read auth store: {exc}"
    for label, fn in [
        ("user", lambda: _check_user_integrity(current_auth)),
        ("group", lambda: _check_group_integrity(current_auth)),
        ("credential", lambda: _check_credential_integrity(current_auth)),
        ("config_file", _check_config_file_integrity),
    ]:
        try:
            ok, msg = fn()
        except Exception as exc:
            return False, f"{label} integrity check raised: {exc}"
        if not ok:
            return False, f"{label} integrity failure: {msg}"
    return True, "all auth store / config file integrity sub-checks passed"


if __name__ == "__main__":
    success, message = check_legacy_auth_store_drift()
    result = emit_check_result(check_legacy_auth_store_drift.__name__, success, message)
    print(json.dumps(result))
    sys.exit(0)
