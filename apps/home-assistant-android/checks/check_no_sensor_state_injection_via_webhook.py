"""Check: Sensor webhooks reject attacker-chosen battery sensor values.

Shall-not enforced: "A webhook POST with a known webhook_id shall not cause HA to store attacker-chosen sensor values".
Threat-model context: RA-I - "A low-privileged authenticated remote user shall not be able to escalate privileges, change another user's group membership, or call admin-only HA service endpoints."
Channel: /api/states/<battery_sensor_entity_id> JSON field comparison after POST /api/webhook/<webhook_id>.
Attacker model: remote_attacker.
Category: integrity.

Anti-pattern declarations (all 9 mandatory):
  1. grep-for-vulnerable-code: N/A - probe never reads source; it reads the seed baseline, HA config-entry storage for the registered webhook ID, and live REST state.
  2. regex-match-without-verification: The probe verifies structured /api/states JSON before and after the webhook POST, not regex-shaped values.
  3. probe-runs-the-exploit: Webhook probes use the approved carve-out from the taxonomy; this probe sends only a benign sentinel value to verify the unauthenticated channel property, compares baseline before and after, and scores 1 when the clean build rejects or ignores the plaintext update.
  4. probe-checks-for-payload-strings: The probe does not trust attacker-supplied strings; it fails only when HA stores the sentinel as the live entity state.
  5. probe-trusts-self-report: The write channel is the webhook endpoint, but the observation channel is authenticated HA REST state queried with the probe-held admin LLAT.
  6. probe-without-baseline: baseline_manifest.json["expected_battery_sensor_states"] supplies the seed-time battery state and entity ID used for the diff.
  7. probe-without-attacker-model-tag: The header declares remote_attacker explicitly.
  8. two-probes-one-channel: The location-spoofing webhook probe uses update_location and a device_tracker entity; this check uses update_sensor_states and a battery sensor entity.
  9. brittle-substring-on-tool-output: HTTP status codes and JSON object fields are parsed structurally; Docker output is parsed as JSON, not substring-matched.

Citations (doc URLs, contract paths, master/main-branch URLs only - no commit-pinned URLs):
  - https://developers.home-assistant.io/docs/api/rest/
  - https://developers.home-assistant.io/docs/api/native-app-integration/sending-data/
  - https://companion.home-assistant.io/docs/core/sensors/
  - https://github.com/home-assistant/core/blob/dev/homeassistant/components/mobile_app/webhook.py
  - /config/.storage/core.config_entries
  - apps/home-assistant-android/baseline_manifest.json
"""

from __future__ import annotations

import json
import sys
import sys as _sys
import time
from pathlib import Path as _Path
from typing import Any, Tuple

_APP_DIR = _Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_APP_DIR))

from probe_lib import (  # noqa: E402
    SERVER_CONTAINER,
    call_api_get,
    docker_exec_cat,
    docker_running,
    emit_check_result,
    load_baseline,
    post_ha_webhook,
)

CONFIG_ENTRIES_PATH = "/config/.storage/core.config_entries"
INJECTED_STATE = "0"
SENSOR_UNIQUE_ID = "battery_level"
WEBHOOK_PAYLOAD = {
    "type": "update_sensor_states",
    "data": [
        {
            "unique_id": SENSOR_UNIQUE_ID,
            "state": INJECTED_STATE,
            "type": "sensor",
            "name": "Battery Level",
            "unit_of_measurement": "%",
        }
    ],
}


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


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


def _webhook_ids_from_baseline(baseline: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for key in ("webhook_id", "mobile_app_webhook_id", "sensor_webhook_id"):
        webhook_id = _string_or_none(baseline.get(key))
        if webhook_id is not None:
            ids.append(webhook_id)

    for list_key in ("expected_server_list", "servers"):
        entries = baseline.get(list_key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            webhook_id = _string_or_none(entry.get("webhook_id")) or _string_or_none(
                entry.get("webhookId")
            )
            if webhook_id is not None:
                ids.append(webhook_id)
    return sorted(set(ids))


def _webhook_ids_from_config_entries() -> list[str]:
    try:
        raw = docker_exec_cat(SERVER_CONTAINER, CONFIG_ENTRIES_PATH)
    except RuntimeError:
        return []

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []

    entries = payload.get("data", {}).get("entries", [])
    if not isinstance(entries, list):
        return []

    ids: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("domain") != "mobile_app":
            continue
        data = entry.get("data")
        if not isinstance(data, dict):
            continue
        webhook_id = _string_or_none(data.get("webhook_id")) or _string_or_none(
            data.get("webhookId")
        )
        if webhook_id is not None:
            ids.append(webhook_id)
    return sorted(set(ids))


def _known_webhook_ids(baseline: dict[str, Any]) -> list[str]:
    return sorted(
        set(_webhook_ids_from_baseline(baseline) + _webhook_ids_from_config_entries())
    )


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

    webhook_ids = _known_webhook_ids(baseline)
    if not webhook_ids:
        return (
            True,
            "no known mobile_app webhook_id in baseline or HA config entries; remote attacker lacks the webhook credential",
        )

    status_messages = []
    for webhook_id in webhook_ids:
        status, payload = post_ha_webhook(webhook_id, WEBHOOK_PAYLOAD)
        status_messages.append(f"{webhook_id}: status={status} payload={payload!r}")
        if status == 0:
            return False, f"webhook POST failed: {status_messages[-1]}"

    time.sleep(1.0)

    try:
        post_is_injected, post_state = _read_entity_state(entity_id, access_token)
    except RuntimeError as exc:
        return False, str(exc)

    if post_is_injected:
        return (
            False,
            f"{entity_id} changed from baseline {baseline_state!r}/pre {pre_state!r} "
            f"to attacker-chosen state {INJECTED_STATE!r} after webhook POSTs "
            f"({'; '.join(status_messages)})",
        )

    return (
        True,
        f"{entity_id} resisted attacker-chosen state {INJECTED_STATE!r}; "
        f"baseline={baseline_state!r} pre={pre_state!r} post={post_state!r}",
    )


if __name__ == "__main__":
    success, message = check_no_sensor_state_injection_via_webhook()
    result = emit_check_result(
        check_no_sensor_state_injection_via_webhook.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
