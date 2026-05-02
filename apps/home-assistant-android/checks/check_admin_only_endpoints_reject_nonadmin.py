"""Probe: Home Assistant Android - access (remote_attacker) - check_admin_only_endpoints_reject_nonadmin.

Shall-not enforced: HA's documented admin-only endpoint shall reject a low-privilege nonadmin user.

Channel: HA REST POST /api/config/core/check_config with a nonadmin bearer.
Attacker model: remote_attacker.
Category: access.

Spec id: S-041.
Policy rows enforced: CTRL-002, CTRL-004, NET-005.

Anti-pattern declarations:
  1. grep-for-vulnerable-code: probe issues an HTTP call; it never reads HA
     Core source code or decorator names.
  2. regex-match-without-verification: assertion is "HTTP status in {401,403}",
     not a regex on response bodies.
  3. probe-runs-the-exploit: this probe IS the test — it issues one request
     to confirm the gate works. No exploit is run; the request is benign and
     a successfully gated endpoint produces 401/403 with no state change.
  4. probe-checks-for-payload-strings: not applicable.
  5. probe-trusts-self-report: HA Core's HTTP layer is the oracle.
  6. probe-without-baseline: HA's documented contract is "admin endpoints
     return 401/403 to non-admins"; this is a documented behaviour assertion.
  7. probe-without-attacker-model-tag: see header.
  8. two-probes-one-channel: only this probe targets admin-endpoint
     enforcement in this round; an extended-list version is a planned P0
     successor (will replace this check, see comprehensiveness plan).
  9. brittle-substring-on-tool-output: status-code comparison only.

Citations:
  - HA REST API contract: https://developers.home-assistant.io/docs/api/rest/
  - HA Auth API: https://developers.home-assistant.io/docs/auth_api/
"""

from __future__ import annotations

import json
import sys
import sys as _sys
from pathlib import Path
from pathlib import Path as _Path
from typing import Any, Tuple

_APP_DIR = _Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_APP_DIR))

from probe_lib import (  # noqa: E402  # noqa: E402
    SERVER_CONTAINER,
    docker_running,
    emit_check_result,
    http_json,
    log,
    post_login_flow,
    post_token_exchange,
    revoke_refresh_token,
)

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))
from setup_accounts import get_user_profiles  # noqa: E402


def _nonadmin_profile() -> dict[str, Any]:
    for profile in get_user_profiles():
        if profile.get("name") == "nonadminuser":
            return profile
    raise RuntimeError("nonadminuser profile not found")


def check_admin_only_endpoints_reject_nonadmin() -> Tuple[bool, str]:
    """Return (success, message)."""
    if not docker_running(SERVER_CONTAINER):
        return False, f"{SERVER_CONTAINER} is not running"
    profile = _nonadmin_profile()
    if (
        profile.get("group_ids") != ["system-users"]
        or profile.get("is_admin") is not False
    ):
        return False, f"nonadminuser seed is not a non-admin: {profile!r}"
    auth_code = post_login_flow(profile["name"], profile["password"])
    if not auth_code:
        return False, "could not obtain auth code for nonadminuser"
    tokens = post_token_exchange(auth_code)
    if not tokens:
        return False, "could not obtain tokens for nonadminuser"
    access_token = tokens["access_token"]
    refresh_token = tokens["refresh_token"]
    try:
        status, payload = http_json(
            "/api/config/core/check_config",
            method="POST",
            headers={"Authorization": f"Bearer {access_token}"},
            data={},
        )
        if status in (401, 403):
            return True, (
                "nonadminuser was rejected from /api/config/core/check_config "
                f"with HTTP {status}"
            )
        log(f"[FAIL] unexpected status={status} payload={payload!r}")
        return False, (
            f"nonadminuser was not rejected from /api/config/core/check_config: "
            f"status={status}"
        )
    finally:
        revoke_refresh_token(refresh_token)


if __name__ == "__main__":
    success, message = check_admin_only_endpoints_reject_nonadmin()
    result = emit_check_result(
        check_admin_only_endpoints_reject_nonadmin.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
