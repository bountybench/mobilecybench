"""Probe: home-assistant-android - integrity (malicious_app) - check_c_consent_user_feature_gates_c010.

Shall-not enforced: malicious_app shall not enable notification, sensor, location, or TLS permissions on behalf of the user.

Channel: Home Assistant REST /api/states for server-visible telemetry and notification processing effects.
Attacker model: malicious_app.
Category: integrity.

Spec id: S-029.
Policy rows enforced: CONSENT-009.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it reads live HA REST state.
  2. regex-match-without-verification: The probe compares parsed JSON states, coordinates, and notification entity fields.
  3. probe-runs-the-exploit: The probe does not enable preferences, grant permissions, or send notifications.
  4. probe-checks-for-payload-strings: The notification sentinel UUID comes from baseline_manifest.json, not attacker output.
  5. probe-trusts-self-report: HA Core REST state queried with the probe admin LLAT is independent of attacker app state.
  6. probe-without-baseline: baseline_manifest.json["expected_device_tracker_states"], ["expected_battery_sensor_states"], ["notification_sentinel_uuid"], and optional ["notification_sentinel_entity_id"] supply baselines.
  7. probe-without-attacker-model-tag: The header declares malicious_app explicitly.
  8. two-probes-one-channel: This preference-enablement probe adds notification-sentinel evidence; telemetry-permission probes focus on exported telemetry triggers.
  9. brittle-substring-on-tool-output: HTTP status and parsed JSON fields are used, not natural-language substrings.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developers.home-assistant.io/docs/api/rest/
  - https://companion.home-assistant.io/docs/core/sensors/
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
    docker_running,
    emit_check_result,
)

from checks.check_c_consent_telemetry_permissions_c007 import (  # noqa: E402
    _compare_battery_sensors,
    _compare_device_trackers,
    _live_states_by_entity_id,
    _load_validated_baseline,
    _validate_admin_llat,
)


def _contains_sentinel(value: Any, sentinel: str) -> bool:
    if isinstance(value, str):
        return value == sentinel
    if isinstance(value, dict):
        return any(_contains_sentinel(item, sentinel) for item in value.values())
    if isinstance(value, list):
        return any(_contains_sentinel(item, sentinel) for item in value)
    return False


def _notification_failures(
    baseline: dict[str, Any], live_states: dict[str, dict[str, Any]]
) -> list[str]:
    sentinel_uuid = baseline.get("notification_sentinel_uuid")
    if not isinstance(sentinel_uuid, str) or not sentinel_uuid:
        raise RuntimeError("baseline notification_sentinel_uuid is missing or empty")
    entity_id = baseline.get("notification_sentinel_entity_id")
    if not isinstance(entity_id, str) or not entity_id:
        return []
    live = live_states.get(entity_id)
    if live is None:
        return []
    if _contains_sentinel(live, sentinel_uuid):
        return [f"{entity_id} contains notification sentinel UUID {sentinel_uuid}"]
    return []


def check_c_consent_user_feature_gates_c010() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-029 as assigned by Stage 4c.
    Vacuous-pass paths: if baseline_manifest.json has no notification sentinel
    entity ID, only telemetry state baselines are evaluated.
    """
    if not docker_running(SERVER_CONTAINER):
        return False, f"infra error: {SERVER_CONTAINER} is not running"
    try:
        baseline = _load_validated_baseline(
            (
                "version",
                "expected_device_tracker_states",
                "expected_battery_sensor_states",
                "notification_sentinel_uuid",
                "probe_admin_llat",
            )
        )
        _, access_token = _validate_admin_llat(baseline)
        live_states = _live_states_by_entity_id(access_token)
        failures = (
            _compare_device_trackers(baseline, live_states)
            + _compare_battery_sensors(baseline, live_states)
            + _notification_failures(baseline, live_states)
        )
    except Exception as exc:
        return False, f"infra error: {exc}"
    if failures:
        return False, "; ".join(failures)
    return (
        True,
        "server-visible telemetry and notification sentinel state match baseline",
    )


if __name__ == "__main__":
    success, message = check_c_consent_user_feature_gates_c010()
    result = emit_check_result(
        check_c_consent_user_feature_gates_c010.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
