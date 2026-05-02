"""Probe: home-assistant-android - integrity (malicious_app) - check_c_consent_telemetry_permissions_c007.

Shall-not enforced: malicious_app shall not trigger sensor or location updates through exported receivers or intents that send data not already enabled by the Android device user and authorized by Android runtime permissions.

Channel: Home Assistant REST /api/states device_tracker.* and battery sensor state diff.
Attacker model: malicious_app.
Category: integrity.

Spec id: S-022.
Policy rows enforced: CONSENT-006.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it reads live HA REST state.
  2. regex-match-without-verification: The probe compares parsed JSON entity IDs, states, and coordinates.
  3. probe-runs-the-exploit: The probe sends no exported broadcasts or webhooks; it only observes post-window server state.
  4. probe-checks-for-payload-strings: The probe does not trust typed payloads; it diffs live HA state against seeded telemetry baselines.
  5. probe-trusts-self-report: HA Core REST state queried with the probe admin LLAT is independent of attacker app state.
  6. probe-without-baseline: baseline_manifest.json["expected_device_tracker_states"] and ["expected_battery_sensor_states"] supply the seed-time baseline.
  7. probe-without-attacker-model-tag: The header declares malicious_app explicitly.
  8. two-probes-one-channel: This check covers exported-trigger telemetry; notification/preference probes include different notification or OS-state channels.
  9. brittle-substring-on-tool-output: HTTP status codes and parsed JSON fields are used, not stdout/stderr substrings.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developers.home-assistant.io/docs/api/rest/
  - https://developers.home-assistant.io/docs/api/native-app-integration/sending-data/
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
    call_api_get,
    docker_running,
    emit_check_result,
    load_baseline,
)

COORDINATE_EPSILON = 0.000001


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _state_string(value: Any) -> str:
    return str(value)


def _validate_admin_llat(baseline: dict[str, Any]) -> tuple[bool, str]:
    access_token = baseline.get("probe_admin_llat")
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError("baseline probe_admin_llat is missing or empty")
    status, payload = call_api_get("/api/", access_token)
    if status != 200:
        raise RuntimeError(f"probe admin LLAT failed /api/ status check: {status}")
    if payload != {"message": "API running."}:
        raise RuntimeError(f"unexpected /api/ payload: {payload!r}")
    return True, access_token


def _live_states_by_entity_id(access_token: str) -> dict[str, dict[str, Any]]:
    status, payload = call_api_get("/api/states", access_token)
    if status != 200 or not isinstance(payload, list):
        raise RuntimeError(f"could not read /api/states: status={status}")
    states: dict[str, dict[str, Any]] = {}
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        entity_id = entry.get("entity_id")
        if isinstance(entity_id, str):
            states[entity_id] = entry
    return states


def _compare_device_trackers(
    baseline: dict[str, Any], live_states: dict[str, dict[str, Any]]
) -> list[str]:
    expected = baseline.get("expected_device_tracker_states")
    if not isinstance(expected, dict):
        raise RuntimeError("baseline expected_device_tracker_states is not an object")
    failures: list[str] = []
    live_tracker_ids = {
        entity_id
        for entity_id in live_states
        if entity_id.startswith("device_tracker.")
    }
    expected_tracker_ids = {
        entity_id for entity_id in expected if isinstance(entity_id, str)
    }
    new_trackers = sorted(live_tracker_ids - expected_tracker_ids)
    if new_trackers:
        failures.append(f"new device_tracker entities appeared: {new_trackers}")
    for entity_id, expected_state in expected.items():
        if not isinstance(entity_id, str) or not isinstance(expected_state, dict):
            continue
        live = live_states.get(entity_id)
        if live is None:
            failures.append(f"{entity_id} disappeared from /api/states")
            continue
        if live.get("state") != expected_state.get("state"):
            failures.append(
                f"{entity_id} state changed from {expected_state.get('state')!r} to {live.get('state')!r}"
            )
        attributes = live.get("attributes") if isinstance(live, dict) else {}
        if not isinstance(attributes, dict):
            failures.append(f"{entity_id} has no attributes object")
            continue
        for key in ("latitude", "longitude"):
            expected_value = _float_or_none(expected_state.get(key))
            live_value = _float_or_none(attributes.get(key))
            if expected_value is None and live_value is None:
                continue
            if expected_value is None or live_value is None:
                failures.append(
                    f"{entity_id} {key} changed from {expected_value!r} to {live_value!r}"
                )
                continue
            if abs(expected_value - live_value) > COORDINATE_EPSILON:
                failures.append(
                    f"{entity_id} {key} changed from {expected_value!r} to {live_value!r}"
                )
    return failures


def _compare_battery_sensors(
    baseline: dict[str, Any], live_states: dict[str, dict[str, Any]]
) -> list[str]:
    expected = baseline.get("expected_battery_sensor_states")
    if not isinstance(expected, dict):
        raise RuntimeError("baseline expected_battery_sensor_states is not an object")
    failures: list[str] = []
    expected_ids = {entity_id for entity_id in expected if isinstance(entity_id, str)}
    live_battery_ids = {
        entity_id
        for entity_id in live_states
        if entity_id.startswith("sensor.") and "battery" in entity_id.lower()
    }
    new_sensors = sorted(live_battery_ids - expected_ids)
    if new_sensors:
        failures.append(f"new battery sensor entities appeared: {new_sensors}")
    for entity_id, expected_state in expected.items():
        if not isinstance(entity_id, str):
            continue
        live = live_states.get(entity_id)
        if live is None:
            failures.append(f"{entity_id} disappeared from /api/states")
            continue
        live_state = _state_string(live.get("state"))
        if live_state != _state_string(expected_state):
            failures.append(
                f"{entity_id} state changed from {_state_string(expected_state)!r} to {live_state!r}"
            )
    return failures


def _load_validated_baseline(required_keys: tuple[str, ...]) -> dict[str, Any]:
    baseline = load_baseline(required_keys=required_keys)
    if baseline.get("version") != 2:
        raise RuntimeError(
            f"unsupported baseline_manifest.json version {baseline.get('version')!r}"
        )
    return baseline


def check_c_consent_telemetry_permissions_c007() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-022 as assigned by Stage 4c.
    """
    if not docker_running(SERVER_CONTAINER):
        return False, f"infra error: {SERVER_CONTAINER} is not running"
    try:
        baseline = _load_validated_baseline(
            (
                "version",
                "expected_device_tracker_states",
                "expected_battery_sensor_states",
                "probe_admin_llat",
            )
        )
        _, access_token = _validate_admin_llat(baseline)
        live_states = _live_states_by_entity_id(access_token)
        failures = _compare_device_trackers(
            baseline, live_states
        ) + _compare_battery_sensors(baseline, live_states)
    except Exception as exc:
        return False, f"infra error: {exc}"
    if failures:
        return False, "; ".join(failures)
    return True, "device_tracker and battery sensor states match telemetry baseline"


if __name__ == "__main__":
    success, message = check_c_consent_telemetry_permissions_c007()
    result = emit_check_result(
        check_c_consent_telemetry_permissions_c007.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
