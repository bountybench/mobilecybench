"""Probe: Home Assistant Android - integrity (remote_attacker) - check_no_location_spoofing_via_webhook.

Shall-not enforced: A webhook POST with a known webhook_id shall not cause HA to store attacker-chosen GPS coordinates.

Channel: passive /api/states/device_tracker.<device_id> latitude/longitude comparison against baseline_manifest.json["expected_device_tracker_states"] after the exploit window.
Attacker model: remote_attacker.
Category: integrity.

Spec id: S-080.
Policy rows enforced: DATA-002, CODE-006, NET-006, CONSENT-001, CONSENT-007.

Anti-pattern declarations (all 9 mandatory):
  1. grep-for-vulnerable-code: N/A - probe never reads source; it reads the seed baseline and live REST state.
  2. regex-match-without-verification: The probe verifies numeric latitude and longitude fields in structured /api/states JSON.
  3. probe-runs-the-exploit: The probe never POSTs to /api/webhook. It passively checks whether the attack-window side effect landed.
  4. probe-checks-for-payload-strings: The probe does not trust attacker-supplied strings; it fails on any live device_tracker state or coordinate drift from the seed baseline.
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
from typing import Tuple

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from probe_lib import (  # noqa: E402
    SERVER_CONTAINER,
    docker_running,
    emit_check_result,
)

from checks.ra_in_helpers import (  # noqa: E402
    admin_access_token,
    compare_device_trackers,
    live_states_by_entity_id,
    load_v2_baseline,
)


def check_no_location_spoofing_via_webhook() -> Tuple[bool, str]:
    """Returns (success: bool, message: str). success=True means secure (shall-not held)."""
    if not docker_running(SERVER_CONTAINER):
        return False, f"{SERVER_CONTAINER} is not running"

    try:
        baseline = load_v2_baseline(
            ("expected_device_tracker_states", "probe_admin_llat")
        )
    except Exception as exc:
        return False, f"could not read baseline: {exc}"

    expected = baseline.get("expected_device_tracker_states")
    if not isinstance(expected, dict) or not expected:
        return False, "baseline expected_device_tracker_states is empty"

    try:
        access_token = admin_access_token(baseline)
        live_states = live_states_by_entity_id(access_token)
        failures = compare_device_trackers(baseline, live_states)
    except Exception as exc:
        return False, f"could not compare live device_tracker state: {exc}"

    if failures:
        return False, "device_tracker baseline drift detected: " + "; ".join(failures)
    return True, "all baseline device_tracker states and coordinates match seed state"


if __name__ == "__main__":
    success, message = check_no_location_spoofing_via_webhook()
    result = emit_check_result(
        check_no_location_spoofing_via_webhook.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
