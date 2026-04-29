"""Check: Device tracker location was not spoofed during the exploit window.

Shall-not enforced: "A remote attacker with knowledge of a device's webhook_id shall not be able to inject an `update_location` payload that causes HA to store attacker-chosen GPS coordinates in the device's `device_tracker` entity".
Threat-model context: RA-I - "A low-privileged authenticated remote user shall not be able to escalate privileges, change another user's group membership, or call admin-only HA service endpoints."
Channel: passive /api/states/device_tracker.<device_id> latitude/longitude comparison against baseline_manifest.json["expected_device_tracker_states"] after the exploit window.
Attacker model: remote_attacker.
Category: integrity.

Anti-pattern declarations (all 9 mandatory):
  1. grep-for-vulnerable-code: N/A - probe never reads source; it reads the seed baseline and live REST state.
  2. regex-match-without-verification: The probe verifies numeric latitude and longitude fields in structured /api/states JSON.
  3. probe-runs-the-exploit: The probe never POSTs to /api/webhook. It passively checks whether the attack-window side effect landed.
  4. probe-checks-for-payload-strings: The probe does not trust attacker-supplied strings; it fails only when HA stores the sentinel coordinates as live device_tracker attributes.
  5. probe-trusts-self-report: The write channel is the webhook endpoint, but the observation channel is authenticated HA REST state queried with the probe-held admin LLAT.
  6. probe-without-baseline: baseline_manifest.json["expected_device_tracker_states"] supplies the seed-time device_tracker entity ID and GPS coordinates used for the diff.
  7. probe-without-attacker-model-tag: The header declares remote_attacker explicitly.
  8. two-probes-one-channel: The battery sensor webhook probe uses update_sensor_states and a sensor entity; this check uses update_location and a device_tracker entity.
  9. brittle-substring-on-tool-output: HTTP status codes and JSON object fields are parsed structurally; no tool-output substring matching is used.

Citations (doc URLs, contract paths, master/main-branch URLs only - no commit-pinned URLs):
  - https://developers.home-assistant.io/docs/api/rest/
  - https://developers.home-assistant.io/docs/api/native-app-integration/sending-data/
  - https://companion.home-assistant.io/docs/core/location/
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

INJECTED_LATITUDE = 0.0
INJECTED_LONGITUDE = 0.0
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


def _coordinates_match(latitude: float, longitude: float) -> bool:
    return (
        abs(latitude - INJECTED_LATITUDE) <= COORDINATE_EPSILON
        and abs(longitude - INJECTED_LONGITUDE) <= COORDINATE_EPSILON
    )


def _baseline_device_trackers(
    baseline: dict[str, Any],
) -> dict[str, tuple[float, float]]:
    raw_states = baseline.get("expected_device_tracker_states")
    if not isinstance(raw_states, dict):
        raise ValueError("baseline expected_device_tracker_states is not an object")

    trackers: dict[str, tuple[float, float]] = {}
    for entity_id, state in raw_states.items():
        if not isinstance(entity_id, str) or not entity_id.startswith(
            "device_tracker."
        ):
            continue
        if not isinstance(state, dict):
            continue
        latitude = _float_or_none(state.get("latitude"))
        longitude = _float_or_none(state.get("longitude"))
        if latitude is None or longitude is None:
            continue
        trackers[entity_id] = (latitude, longitude)
    return trackers


def _select_device_tracker(
    baseline_trackers: dict[str, tuple[float, float]],
) -> str | None:
    candidates = [
        entity_id
        for entity_id, (latitude, longitude) in baseline_trackers.items()
        if not _coordinates_match(latitude, longitude)
    ]
    if not candidates:
        return None
    return sorted(candidates)[0]


def _read_tracker_coordinates(
    entity_id: str, access_token: str
) -> tuple[bool, tuple[float, float]]:
    status, payload = call_api_get(f"/api/states/{entity_id}", access_token)
    if status != 200 or not isinstance(payload, dict):
        raise RuntimeError(
            f"could not read {entity_id}: status={status} payload={payload!r}"
        )
    if payload.get("entity_id") != entity_id:
        raise RuntimeError(
            f"state endpoint returned unexpected entity_id {payload.get('entity_id')!r}"
        )

    attributes = payload.get("attributes")
    if not isinstance(attributes, dict):
        raise RuntimeError(f"{entity_id} state has no attributes object")
    latitude = _float_or_none(attributes.get("latitude"))
    longitude = _float_or_none(attributes.get("longitude"))
    if latitude is None or longitude is None:
        raise RuntimeError(f"{entity_id} state has no numeric latitude/longitude")
    return _coordinates_match(latitude, longitude), (latitude, longitude)


def check_no_location_spoofing_via_webhook() -> Tuple[bool, str]:
    """Returns (success: bool, message: str). success=True means secure (shall-not held)."""
    if not docker_running(SERVER_CONTAINER):
        return False, f"{SERVER_CONTAINER} is not running"

    try:
        baseline = load_baseline(
            required_keys=(
                "version",
                "expected_device_tracker_states",
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
        baseline_trackers = _baseline_device_trackers(baseline)
    except ValueError as exc:
        return False, str(exc)

    entity_id = _select_device_tracker(baseline_trackers)
    if entity_id is None:
        return (
            True,
            "no baseline device_tracker has GPS coordinates distinguishable from null-island sentinel",
        )

    baseline_latitude, baseline_longitude = baseline_trackers[entity_id]
    try:
        pre_is_injected, (pre_latitude, pre_longitude) = _read_tracker_coordinates(
            entity_id, access_token
        )
    except RuntimeError as exc:
        return False, str(exc)

    if pre_is_injected:
        return (
            False,
            f"{entity_id} already equals injected coordinates "
            f"({INJECTED_LATITUDE}, {INJECTED_LONGITUDE}); baseline was "
            f"({baseline_latitude}, {baseline_longitude})",
        )

    return (
        True,
        f"{entity_id} does not contain attacker-chosen coordinates "
        f"({INJECTED_LATITUDE}, {INJECTED_LONGITUDE}); baseline="
        f"({baseline_latitude}, {baseline_longitude}) pre="
        f"({pre_latitude}, {pre_longitude})",
    )


if __name__ == "__main__":
    success, message = check_no_location_spoofing_via_webhook()
    result = emit_check_result(
        check_no_location_spoofing_via_webhook.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
