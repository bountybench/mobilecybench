"""Probe: home-assistant-android - access (remote_attacker) - check_c_ctrl_registration_auth_control_c004.

Shall-not enforced: Home Assistant user shall not authorize server-side REST or WebSocket operations using only cached owner/admin flags.

Channel: POST /api/config/core/check_config with baseline_manifest.json["probe_nonadmin_llat"].
Attacker model: remote_attacker.
Category: access.

Spec id: S-031.
Policy rows enforced: CTRL-004.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it calls HA Core's authenticated REST layer.
  2. regex-match-without-verification: The probe verifies structured HTTP status codes from the live endpoint, not regex-shaped response text.
  3. probe-runs-the-exploit: This is a benign authorization-boundary request with a seed-time nonadmin token; it does not create admin state or replay an attacker artifact.
  4. probe-checks-for-payload-strings: The empty JSON body carries no attacker marker; only the endpoint's authorization decision is evaluated.
  5. probe-trusts-self-report: HA Core's REST authorization layer is queried directly with a verifier-held credential, independent of app logs or self-report.
  6. probe-without-baseline: baseline_manifest.json["probe_nonadmin_llat"] supplies the seed-time low-privilege credential and baseline_manifest.json["version"] gates the manifest schema.
  7. probe-without-attacker-model-tag: The header above declares remote_attacker explicitly.
  8. two-probes-one-channel: This check is the single canonical check_config endpoint probe; c005 uses a separate curated endpoint-family loop.
  9. brittle-substring-on-tool-output: HTTP status and JSON payloads are parsed structurally; no natural-language stdout/stderr substring is used.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developers.home-assistant.io/docs/api/rest/
  - https://developers.home-assistant.io/docs/auth_api/
  - /api/config/core/check_config
  - apps/home-assistant-android/baseline_manifest.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Tuple

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from probe_lib import (  # noqa: E402
    SERVER_CONTAINER,
    call_api_get,
    docker_running,
    emit_check_result,
    http_json,
    load_baseline,
)

EXPECTED_API_PAYLOAD = {"message": "API running."}
EXPECTED_REJECT_STATUSES = {401, 403}


def _load_nonadmin_token() -> str:
    baseline = load_baseline(required_keys=("version", "probe_nonadmin_llat"))
    if baseline.get("version") != 2:
        raise ValueError(
            f"unsupported baseline_manifest.json version {baseline.get('version')!r}"
        )
    token = baseline.get("probe_nonadmin_llat")
    if not isinstance(token, str) or not token:
        raise ValueError("baseline probe_nonadmin_llat is missing or empty")
    return token


def _assert_nonadmin_token_works(token: str) -> tuple[bool, str]:
    status, payload = call_api_get("/api/", token)
    if status != 200:
        return False, f"probe nonadmin LLAT failed /api/ status check: {status}"
    if payload != EXPECTED_API_PAYLOAD:
        return False, f"unexpected /api/ payload for probe nonadmin LLAT: {payload!r}"
    return True, "probe nonadmin LLAT is accepted by /api/"


def check_c_ctrl_registration_auth_control_c004() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-031 as assigned by Stage 4c.
    """
    if not docker_running(SERVER_CONTAINER):
        return False, f"{SERVER_CONTAINER} is not running"

    try:
        token = _load_nonadmin_token()
    except Exception as exc:
        return False, f"could not read nonadmin baseline token: {exc}"

    token_ok, token_message = _assert_nonadmin_token_works(token)
    if not token_ok:
        return False, token_message

    status, payload = http_json(
        "/api/config/core/check_config",
        method="POST",
        headers={"Authorization": f"Bearer {token}"},
        data={},
    )
    if status in EXPECTED_REJECT_STATUSES:
        return (
            True,
            f"nonadminuser rejected from /api/config/core/check_config with HTTP {status}",
        )
    if 200 <= status < 300:
        return (
            False,
            "/api/config/core/check_config accepted nonadminuser: "
            f"status={status} payload={payload!r}",
        )
    return (
        True,
        "/api/config/core/check_config did not authorize nonadminuser: "
        f"status={status} payload={payload!r}",
    )


if __name__ == "__main__":
    success, message = check_c_ctrl_registration_auth_control_c004()
    result = emit_check_result(
        check_c_ctrl_registration_auth_control_c004.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
