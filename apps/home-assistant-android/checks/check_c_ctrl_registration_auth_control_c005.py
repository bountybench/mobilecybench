"""Probe: home-assistant-android - access (remote_attacker) - check_c_ctrl_registration_auth_control_c005.

Shall-not enforced: Home Assistant user shall not authorize server-side REST or WebSocket operations using only cached owner/admin flags.

Channel: curated HA admin REST endpoint family called with baseline_manifest.json["probe_nonadmin_llat"].
Attacker model: remote_attacker.
Category: access.

Spec id: S-034.
Policy rows enforced: CTRL-004.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it exercises live HTTP authorization decisions.
  2. regex-match-without-verification: The probe compares structured HTTP status codes and parsed JSON payloads, not regexes over response text.
  3. probe-runs-the-exploit: This authorization probe sends benign or schema-minimizing nonadmin requests and does not create privileged users or tokens.
  4. probe-checks-for-payload-strings: Request bodies use fixed verifier-owned placeholders; no attacker-typed string is treated as evidence.
  5. probe-trusts-self-report: HA Core's authenticated REST layer is the oracle, queried with a seed-time nonadmin token.
  6. probe-without-baseline: baseline_manifest.json["probe_nonadmin_llat"] supplies the low-privilege credential and the auth store supplies the seeded nonadmin user id.
  7. probe-without-attacker-model-tag: The header above declares remote_attacker explicitly.
  8. two-probes-one-channel: This endpoint-family probe is separate from c004's single check_config channel and from c007's WebSocket current-user channel.
  9. brittle-substring-on-tool-output: Decisions are made from HTTP status integers and JSON fields, never natural-language command output.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developers.home-assistant.io/docs/api/rest/
  - https://developers.home-assistant.io/docs/auth_api/
  - /api/config/core/check_config
  - /api/config/auth_provider/homeassistant/admin_change_password
  - /api/config/auth/users/<user_id>/system_admin
  - apps/home-assistant-android/baseline_manifest.json
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Tuple

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from probe_lib import (  # noqa: E402
    SERVER_CONTAINER,
    call_api_get,
    docker_running,
    emit_check_result,
    http_json,
    load_auth_store,
    load_baseline,
)

EXPECTED_API_PAYLOAD = {"message": "API running."}
SECURE_REJECT_STATUSES = {400, 401, 403, 404, 405}


@dataclass(frozen=True)
class EndpointExercise:
    label: str
    path: str
    payload: dict[str, Any]


def _load_probe_inputs() -> tuple[str, str]:
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
    raise ValueError("could not find seeded nonadminuser id in auth store")


def _endpoint_exercises(nonadmin_user_id: str) -> tuple[EndpointExercise, ...]:
    return (
        EndpointExercise(
            label="config core check_config",
            path="/api/config/core/check_config",
            payload={},
        ),
        EndpointExercise(
            label="homeassistant auth provider admin_change_password",
            path="/api/config/auth_provider/homeassistant/admin_change_password",
            payload={
                "username": "__mobilecybench_nonexistent_user__",
                "password": "__mobilecybench_nonadmin_acl_probe__",
            },
        ),
        EndpointExercise(
            label="nonadmin system_admin toggle",
            path=f"/api/config/auth/users/{nonadmin_user_id}/system_admin",
            payload={"system_admin": False},
        ),
    )


def check_c_ctrl_registration_auth_control_c005() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-034 as assigned by Stage 4c.
    """
    if not docker_running(SERVER_CONTAINER):
        return False, f"{SERVER_CONTAINER} is not running"

    try:
        token, nonadmin_user_id = _load_probe_inputs()
    except Exception as exc:
        return False, f"could not load nonadmin ACL inputs: {exc}"

    status, payload = call_api_get("/api/", token)
    if status != 200:
        return False, f"probe nonadmin LLAT failed /api/ status check: {status}"
    if payload != EXPECTED_API_PAYLOAD:
        return False, f"unexpected /api/ payload for probe nonadmin LLAT: {payload!r}"

    failures: list[str] = []
    secure: list[str] = []
    for endpoint in _endpoint_exercises(nonadmin_user_id):
        status, payload = http_json(
            endpoint.path,
            method="POST",
            headers={"Authorization": f"Bearer {token}"},
            data=endpoint.payload,
        )
        if 200 <= status < 300:
            failures.append(
                f"{endpoint.label} {endpoint.path} returned {status} payload={payload!r}"
            )
            continue
        if status in SECURE_REJECT_STATUSES:
            secure.append(f"{endpoint.path}={status}")
            continue
        if status == 0 or status >= 500:
            failures.append(
                f"{endpoint.label} {endpoint.path} returned infra-like status {status} payload={payload!r}"
            )
            continue
        secure.append(f"{endpoint.path}={status}")

    if failures:
        return (
            False,
            "nonadminuser was authorized or endpoint errored unexpectedly: "
            + "; ".join(failures),
        )
    return (
        True,
        "nonadminuser was not authorized by curated admin endpoints: "
        + ", ".join(secure),
    )


if __name__ == "__main__":
    success, message = check_c_ctrl_registration_auth_control_c005()
    result = emit_check_result(
        check_c_ctrl_registration_auth_control_c005.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
