"""Probe: home-assistant-android - outbound mobile events (remote_attacker) - check_c_data_outbound_mobile_events_c003.

Shall-not enforced: Android device user shall not send device location to Home Assistant unless location tracking and Android location permission are enabled for the registered server.

Channel: Home Assistant REST /api/states device_tracker.* state and coordinate diff.
Attacker model: remote_attacker.
Category: integrity.

Spec id: S-068.
Policy rows enforced: DATA-002.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source; it reads HA REST state.
  2. regex-match-without-verification: The probe compares parsed JSON entity IDs and coordinate fields.
  3. probe-runs-the-exploit: The probe does not trigger location sync; it observes server state after the tested window.
  4. probe-checks-for-payload-strings: No payload strings are trusted; only persisted device_tracker state is evidence.
  5. probe-trusts-self-report: HA Core REST state is queried by the verifier with a seed LLAT.
  6. probe-without-baseline: baseline_manifest.json["expected_device_tracker_states"] supplies the seed-time location baseline.
  7. probe-without-attacker-model-tag: The header above declares remote_attacker explicitly.
  8. two-probes-one-channel: This REST final-state channel is distinct from the WebSocket event probe for transient updates.
  9. brittle-substring-on-tool-output: HTTP status codes and parsed JSON fields drive the result.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developers.home-assistant.io/docs/api/rest/
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

from probe_lib import emit_check_result  # noqa: E402

from checks.ra_in_helpers import check_rest_telemetry  # noqa: E402


def check_c_data_outbound_mobile_events_c003() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held)."""
    try:
        return check_rest_telemetry(include_location=True, include_sensors=False)
    except Exception as exc:
        return False, f"infra error: {exc}"


if __name__ == "__main__":
    success, message = check_c_data_outbound_mobile_events_c003()
    print(
        json.dumps(
            emit_check_result(
                check_c_data_outbound_mobile_events_c003.__name__, success, message
            )
        )
    )
    sys.exit(0)
