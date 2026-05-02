"""Probe: home-assistant-android - telemetry permissions (remote_attacker) - check_c_consent_telemetry_permissions_c001.

Shall-not enforced: Android device user shall not cause update_location data to leave the device unless onboarding or settings enable location tracking and Android location permission is granted.

Channel: Home Assistant REST /api/states device_tracker.* state and coordinate diff.
Attacker model: remote_attacker.
Category: integrity.

Spec id: S-066.
Policy rows enforced: CONSENT-001.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it reads HA REST state.
  2. regex-match-without-verification: The probe compares parsed JSON entity IDs, states, latitude, and longitude.
  3. probe-runs-the-exploit: The probe does not trigger location updates; it observes post-window server state.
  4. probe-checks-for-payload-strings: No attacker-provided strings are trusted; only server-side device_tracker state matters.
  5. probe-trusts-self-report: HA Core REST state queried with a probe LLAT is independent of app or attacker self-report.
  6. probe-without-baseline: baseline_manifest.json["expected_device_tracker_states"] supplies the seed-time location baseline.
  7. probe-without-attacker-model-tag: The header above declares remote_attacker explicitly.
  8. two-probes-one-channel: This final-state REST diff is paired with the WebSocket transient-event check for a distinct observation channel.
  9. brittle-substring-on-tool-output: HTTP status codes and parsed JSON fields drive the result, not stdout/stderr substrings.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
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

from probe_lib import emit_check_result  # noqa: E402

from checks.ra_in_helpers import check_rest_telemetry  # noqa: E402


def check_c_consent_telemetry_permissions_c001() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held)."""
    try:
        return check_rest_telemetry(include_location=True, include_sensors=False)
    except Exception as exc:
        return False, f"infra error: {exc}"


if __name__ == "__main__":
    success, message = check_c_consent_telemetry_permissions_c001()
    print(
        json.dumps(
            emit_check_result(
                check_c_consent_telemetry_permissions_c001.__name__, success, message
            )
        )
    )
    sys.exit(0)
