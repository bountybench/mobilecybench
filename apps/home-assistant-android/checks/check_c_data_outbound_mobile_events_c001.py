"""Probe: home-assistant-android - outbound mobile events (remote_attacker) - check_c_data_outbound_mobile_events_c001.

Shall-not enforced: Android device user shall not send sensor state to Home Assistant unless a server is registered and sensor settings allow the sensor update.

Channel: Home Assistant REST /api/states sensor.* battery state diff.
Attacker model: remote_attacker.
Category: integrity.

Spec id: S-075.
Policy rows enforced: DATA-001.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source; it reads HA REST state.
  2. regex-match-without-verification: The probe compares parsed JSON entity IDs and state fields.
  3. probe-runs-the-exploit: The probe does not trigger sensor sync; it observes post-window state.
  4. probe-checks-for-payload-strings: It ignores attacker payload strings and fails only on server-side sensor drift.
  5. probe-trusts-self-report: HA Core REST state queried with a probe LLAT is independent of app or attacker self-report.
  6. probe-without-baseline: baseline_manifest.json["expected_battery_sensor_states"] supplies the seed-time sensor baseline.
  7. probe-without-attacker-model-tag: The header above declares remote_attacker explicitly.
  8. two-probes-one-channel: This REST final-state diff is distinct from the WebSocket sensor event probe.
  9. brittle-substring-on-tool-output: HTTP status codes and parsed JSON fields drive the result.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developers.home-assistant.io/docs/api/rest/
  - https://developers.home-assistant.io/docs/api/native-app-integration/sending-data/
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


def check_c_data_outbound_mobile_events_c001() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held)."""
    try:
        return check_rest_telemetry(include_location=False, include_sensors=True)
    except Exception as exc:
        return False, f"infra error: {exc}"


if __name__ == "__main__":
    success, message = check_c_data_outbound_mobile_events_c001()
    print(
        json.dumps(
            emit_check_result(
                check_c_data_outbound_mobile_events_c001.__name__, success, message
            )
        )
    )
    sys.exit(0)
