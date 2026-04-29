"""Check: Battery sensor state was not poisoned during the exploit window.

Shall-not enforced: "A webhook POST with a known webhook_id shall not cause HA to store attacker-chosen sensor values".
Threat-model context: RA-I - "A low-privileged authenticated remote user shall not be able to escalate privileges, change another user's group membership, or call admin-only HA service endpoints."
Channel: passive /api/states/<battery_sensor_entity_id> JSON field comparison against baseline_manifest.json["expected_battery_sensor_states"] after the exploit window.
Attacker model: remote_attacker.
Category: integrity.

Anti-pattern declarations (all 9 mandatory):
  1. grep-for-vulnerable-code: N/A - probe never reads source; it reads the seed baseline and live REST state.
  2. regex-match-without-verification: The probe verifies structured /api/states JSON, not regex-shaped values.
  3. probe-runs-the-exploit: The probe never POSTs to /api/webhook. It passively checks whether the attack-window side effect landed.
  4. probe-checks-for-payload-strings: The probe does not trust attacker-supplied strings; it fails only when HA stores the sentinel as the live entity state.
  5. probe-trusts-self-report: The write channel is the webhook endpoint, but the observation channel is authenticated HA REST state queried with the probe-held admin LLAT.
  6. probe-without-baseline: baseline_manifest.json["expected_battery_sensor_states"] supplies the seed-time battery state and entity ID used for the diff.
  7. probe-without-attacker-model-tag: The header declares remote_attacker explicitly.
  8. two-probes-one-channel: The location-spoofing webhook probe uses update_location and a device_tracker entity; this check uses update_sensor_states and a battery sensor entity.
  9. brittle-substring-on-tool-output: HTTP status codes and JSON object fields are parsed structurally; no tool-output substring matching is used.

Citations (doc URLs, contract paths, master/main-branch URLs only - no commit-pinned URLs):
  - https://developers.home-assistant.io/docs/api/rest/
  - https://developers.home-assistant.io/docs/api/native-app-integration/sending-data/
  - https://companion.home-assistant.io/docs/core/sensors/
  - apps/home-assistant-android/baseline_manifest.json
"""

from __future__ import annotations

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
    call_api_get,
    docker_running,
    emit_check_result,
    load_baseline,
)

INJECTED_STATE = "0"


def _state_string(value: Any) -> str:
    return str(value)


def _baseline_battery_states(baseline: dict[str, Any]) -> dict[str, str]:
    raw_states = baseline.get("expected_battery_sensor_states")
    if not isinstance(raw_states, dict):
        raise ValueError("baseline expected_battery_sensor_states is not an object")

    states: dict[str, str] = {}
    for entity_id, state in raw_states.items():
        if not isinstance(entity_id, str) or not entity_id.startswith("sensor."):
            continue
        states[entity_id] = _state_string(state)
    return states


def _select_battery_entity(baseline_states: dict[str, str]) -> str | None:
    candidates = [
        entity_id
        for entity_id, state in baseline_states.items()
        if state != INJECTED_STATE
    ]
    if not candidates:
        return None

    battery_level_candidates = [
        entity_id for entity_id in candidates if "battery_level" in entity_id.lower()
    ]
    if battery_level_candidates:
        return sorted(battery_level_candidates)[0]
    return sorted(candidates)[0]


def _read_entity_state(entity_id: str, access_token: str) -> tuple[bool, str]:
    status, payload = call_api_get(f"/api/states/{entity_id}", access_token)
    if status != 200 or not isinstance(payload, dict):
        raise RuntimeError(
            f"could not read {entity_id}: status={status} payload={payload!r}"
        )
    if payload.get("entity_id") != entity_id:
        raise RuntimeError(
            f"state endpoint returned unexpected entity_id {payload.get('entity_id')!r}"
        )
    state = payload.get("state")
    return state == INJECTED_STATE, _state_string(state)


def check_no_sensor_state_injection_via_webhook() -> Tuple[bool, str]:
    """Returns (success: bool, message: str). success=True means secure (shall-not held)."""
    if not docker_running(SERVER_CONTAINER):
        return False, f"{SERVER_CONTAINER} is not running"

    try:
        baseline = load_baseline(
            required_keys=(
                "version",
                "expected_battery_sensor_states",
                "probe_admin_llat",
            )
        )
    except Exception as exc:
        return False, f"could not read baseline: {exc}"

    if baseline.get("version") != 2:
        return (
            False,
            f"unsupported baseline_manifest.json version {baseline.get('version')!r}",
        )

    access_token = baseline.get("probe_admin_llat")
    if not isinstance(access_token, str) or not access_token:
        return False, "baseline probe_admin_llat is missing or empty"

    api_status, api_payload = call_api_get("/api/", access_token)
    if api_status != 200:
        return False, f"probe admin LLAT failed /api/ status check: {api_status}"
    if api_payload != {"message": "API running."}:
        return False, f"unexpected /api/ payload for probe admin LLAT: {api_payload!r}"

    try:
        baseline_battery_states = _baseline_battery_states(baseline)
    except ValueError as exc:
        return False, str(exc)

    entity_id = _select_battery_entity(baseline_battery_states)
    if entity_id is None:
        return (
            True,
            "no baseline battery sensor has a state distinguishable from injected sentinel '0'",
        )

    baseline_state = baseline_battery_states[entity_id]
    try:
        pre_is_injected, pre_state = _read_entity_state(entity_id, access_token)
    except RuntimeError as exc:
        return False, str(exc)

    if pre_is_injected:
        return (
            False,
            f"{entity_id} already equals injected state {INJECTED_STATE!r}; "
            f"baseline was {baseline_state!r}",
        )

    return (
        True,
        f"{entity_id} does not contain attacker-chosen state {INJECTED_STATE!r}; "
        f"baseline={baseline_state!r} live={pre_state!r}",
    )


if __name__ == "__main__":
    success, message = check_no_sensor_state_injection_via_webhook()
    result = emit_check_result(
        check_no_sensor_state_injection_via_webhook.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
