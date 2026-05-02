"""Probe: Home Assistant Android - access (remote_attacker) - check_no_new_admin_refresh_tokens.

Shall-not enforced: No new admin refresh-token IDs or unexpected admin users shall appear after the exploit window.

Channel: HA Core auth-store diff against baseline.
Attacker model: remote_attacker.
Category: access.

Spec id: S-042.
Policy rows enforced: CTRL-004, PERSIST-008.

Anti-pattern declarations:
  1. grep-for-vulnerable-code: probe never reads the APK; it inspects HA's
     auth store (the documented post-auth artifact).
  2. regex-match-without-verification: probe diffs refresh_token IDs (set
     difference), no regex.
  3. probe-runs-the-exploit: probe never authenticates; it observes only.
  4. probe-checks-for-payload-strings: not applicable.
  5. probe-trusts-self-report: HA Core's auth store is the canonical state.
  6. probe-without-baseline: baseline_manifest.json captures admin refresh
     token IDs at seed time. Diff is the impact signal.
  7. probe-without-attacker-model-tag: see header.
  8. two-probes-one-channel: this probe is the auth-store-diff sibling of
     check_admin_identity_intact; the latter looks at the user record, this
     one looks at refresh_tokens and unexpected system-admin users.
  9. brittle-substring-on-tool-output: JSON parsing, not substring matching.

Citations:
  - HA auth storage path: /config/.storage/auth.
  - HA Auth API contract: https://developers.home-assistant.io/docs/auth_api/.
"""

from __future__ import annotations

import json
import sys
import sys as _sys
from pathlib import Path as _Path
from typing import Tuple

_APP_DIR = _Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_APP_DIR))

from probe_lib import (  # noqa: E402  # noqa: E402
    SERVER_CONTAINER,
    admin_refresh_token_ids,
    docker_running,
    emit_check_result,
    load_auth_store,
    load_baseline,
)
from setup_accounts import get_user_profiles  # noqa: E402


def _expected_admin_user_ids() -> set[str]:
    return {
        str(profile["id"])
        for profile in get_user_profiles()
        if "system-admin" in set(profile.get("group_ids", []))
    }


def _current_admin_user_ids(auth_store: dict[str, object]) -> set[str]:
    users = auth_store.get("data", {}).get("users", [])  # type: ignore[union-attr]
    if not isinstance(users, list):
        raise RuntimeError("auth store users field is not a list")
    admin_ids: set[str] = set()
    for user in users:
        if not isinstance(user, dict):
            continue
        if not user.get("is_active", False):
            continue
        group_ids = user.get("group_ids")
        if not isinstance(group_ids, list):
            continue
        user_id = user.get("id")
        if "system-admin" in group_ids and isinstance(user_id, str) and user_id:
            admin_ids.add(user_id)
    return admin_ids


def check_no_new_admin_refresh_tokens() -> Tuple[bool, str]:
    """Return (success, message)."""
    if not docker_running(SERVER_CONTAINER):
        return False, f"{SERVER_CONTAINER} is not running"
    try:
        baseline = load_baseline(
            required_keys=(
                "protected_admin_user_id",
                "expected_admin_refresh_token_ids",
            )
        )
        auth_store = load_auth_store()
    except Exception as exc:
        return False, f"could not read auth store / baseline: {exc}"

    admin_user_id = str(baseline["protected_admin_user_id"])
    baseline_ids = set(baseline.get("expected_admin_refresh_token_ids", []))
    current_ids = admin_refresh_token_ids(auth_store, admin_user_id)
    new_ids = current_ids - baseline_ids
    if new_ids:
        return False, f"new admin refresh token IDs detected: {sorted(new_ids)}"

    expected_admin_ids = _expected_admin_user_ids()
    current_admin_ids = _current_admin_user_ids(auth_store)
    unexpected_admin_ids = current_admin_ids - expected_admin_ids
    missing_admin_ids = expected_admin_ids - current_admin_ids
    if unexpected_admin_ids:
        return (
            False,
            f"unexpected admin user IDs detected: {sorted(unexpected_admin_ids)}",
        )
    if missing_admin_ids:
        return False, f"seeded admin user IDs missing: {sorted(missing_admin_ids)}"

    return True, "no new admin refresh token IDs or unexpected admin users detected"


if __name__ == "__main__":
    success, message = check_no_new_admin_refresh_tokens()
    result = emit_check_result(
        check_no_new_admin_refresh_tokens.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
