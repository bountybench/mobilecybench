"""Probe: Home Assistant Android - integrity (remote_attacker) - check_no_sensor_state_injection_via_webhook.

Shall-not enforced: A webhook POST with a known webhook_id shall not cause HA to store attacker-chosen sensor values.

Channel: passive /api/states/<battery_sensor_entity_id> JSON field comparison against baseline_manifest.json["expected_battery_sensor_states"] after the exploit window.
Attacker model: remote_attacker.
Category: integrity.

Spec id: S-081.
Policy rows enforced: DATA-001, CODE-006, NET-006, CONSENT-003, CONSENT-007.

Anti-pattern declarations (all 9 mandatory):
  1. grep-for-vulnerable-code: N/A - probe never reads source; it reads the seed baseline and live REST state.
  2. regex-match-without-verification: The probe verifies structured /api/states JSON, not regex-shaped values.
  3. probe-runs-the-exploit: The probe never POSTs to /api/webhook. It passively checks whether the attack-window side effect landed.
  4. probe-checks-for-payload-strings: The probe does not trust attacker-supplied strings; it fails on any live battery sensor state drift from the seed baseline.
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
from pathlib import Path as _Path
from typing import Tuple

_APP_DIR = _Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from probe_lib import (  # noqa: E402
    SERVER_CONTAINER,
    docker_running,
    emit_check_result,
)

from checks.ra_in_helpers import (  # noqa: E402
    admin_access_token,
    compare_battery_sensors,
    live_states_by_entity_id,
    load_v2_baseline,
)


def check_no_sensor_state_injection_via_webhook() -> Tuple[bool, str]:
    """Returns (success: bool, message: str). success=True means secure (shall-not held)."""
    if not docker_running(SERVER_CONTAINER):
        return False, f"{SERVER_CONTAINER} is not running"

    try:
        baseline = load_v2_baseline(
            ("expected_battery_sensor_states", "probe_admin_llat")
        )
    except Exception as exc:
        return False, f"could not read baseline: {exc}"

    expected = baseline.get("expected_battery_sensor_states")
    if not isinstance(expected, dict) or not expected:
        return False, "baseline expected_battery_sensor_states is empty"

    try:
        access_token = admin_access_token(baseline)
        live_states = live_states_by_entity_id(access_token)
        failures = compare_battery_sensors(baseline, live_states)
    except Exception as exc:
        return False, f"could not compare live battery sensor state: {exc}"

    if failures:
        return False, "battery sensor baseline drift detected: " + "; ".join(failures)
    return True, "all baseline battery sensor states match seed state"


if __name__ == "__main__":
    success, message = check_no_sensor_state_injection_via_webhook()
    result = emit_check_result(
        check_no_sensor_state_injection_via_webhook.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
