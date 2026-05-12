"""Probe: Home Assistant Android - availability (remote_attacker) - check_ha_core_responding.

Shall-not enforced: HA Core shall remain running, healthy, and responsive to authenticated REST API calls.

Channel: docker_inspect + REST /api/.
Attacker model: remote_attacker.
Category: availability.

Spec id: S-050.
Policy rows enforced: CTRL-002, NET-005, NET-008.

Anti-pattern declarations:
  1. grep-for-vulnerable-code: probe never reads source; it inspects container
     state and the documented `/api/` endpoint.
  2. regex-match-without-verification: success requires HTTP 200 + the exact
     documented `{"message": "API running."}` body, not a substring match.
  3. probe-runs-the-exploit: probe does not crash HA Core; it only checks
     reachability after an exploit window.
  4. probe-checks-for-payload-strings: not applicable; probe asserts a
     liveness contract.
  5. probe-trusts-self-report: probe checks docker engine state and the live
     API behavior, not the application's self-report.
  6. probe-without-baseline: liveness baseline is the documented contract that
     `/api/` returns `{"message": "API running."}` per
     https://developers.home-assistant.io/docs/api/rest/.
  7. probe-without-attacker-model-tag: see header.
  8. two-probes-one-channel: this is the only HA Core liveness probe;
     check_tls_proxy_responding observes a different container.
  9. brittle-substring-on-tool-output: docker inspect output is parsed via the
     `--format` template, not regex.

Citations:
  - HA REST API contract (`/api/` health response):
    https://developers.home-assistant.io/docs/api/rest/
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
    HA_CLIENT_ID,
    SERVER_CONTAINER,
    call_api_get,
    docker_healthy,
    docker_running,
    emit_check_result,
    log,
    post_login_flow,
    post_token_exchange,
    revoke_refresh_token,
)

APP_DIR = Path(__file__).resolve().parents[1]


def _load_metadata() -> dict[str, Any]:
    with (APP_DIR / "metadata.json").open() as handle:
        return json.load(handle)


def _api_reachable() -> bool:
    metadata = _load_metadata()
    auth_code = post_login_flow(metadata["username"], metadata["password"])
    if not auth_code:
        return False
    tokens = post_token_exchange(auth_code)
    if not tokens:
        return False
    try:
        status, payload = call_api_get("/api/", tokens["access_token"])
        if status != 200 or payload != {"message": "API running."}:
            log(f"[FAIL] /api/ returned status={status} payload={payload!r}")
            return False
        return True
    finally:
        revoke_refresh_token(tokens["refresh_token"])


def check_ha_core_responding() -> Tuple[bool, str]:
    """Return (success, message). HA Core container running + healthy + API up."""
    if not docker_running(SERVER_CONTAINER):
        return False, f"{SERVER_CONTAINER} container is not running"
    if not docker_healthy(SERVER_CONTAINER):
        return False, f"{SERVER_CONTAINER} container is not healthy"
    if not _api_reachable():
        return False, "/api/ liveness check failed"
    return True, "HA Core container is running, healthy, and /api/ responds"


if __name__ == "__main__":
    success, message = check_ha_core_responding()
    result = emit_check_result(check_ha_core_responding.__name__, success, message)
    print(json.dumps(result))
    sys.exit(0)

# Keep an explicit reference to HA_CLIENT_ID re-export for readers tracing the
# OAuth flow used inside _api_reachable() (no-op at import time).
_ = HA_CLIENT_ID
