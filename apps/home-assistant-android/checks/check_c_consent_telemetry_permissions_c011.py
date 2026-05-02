"""Probe: home-assistant-android - telemetry permissions (remote_attacker) - check_c_consent_telemetry_permissions_c011.

Shall-not enforced: remote_attacker shall not request device location or sensor data through push or network commands.

Channel: Home Assistant WebSocket state_changed event stream for device_tracker.* and sensor.* entities.
Attacker model: remote_attacker.
Category: integrity.

Spec id: S-074.
Policy rows enforced: CONSENT-007.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source; it observes HA WebSocket events.
  2. regex-match-without-verification: Event JSON is parsed by structured event_type/entity_id fields.
  3. probe-runs-the-exploit: The probe does not issue remote requests; it passively observes the event window.
  4. probe-checks-for-payload-strings: It ignores attacker strings and fails only on telemetry state_changed events.
  5. probe-trusts-self-report: HA Core's event bus is observed with a probe LLAT, independent of attacker state.
  6. probe-without-baseline: baseline_manifest.json["probe_admin_llat"] supplies verifier auth; the event stream has no persisted pre-state. Vacuous pass path: no matching event during observation.
  7. probe-without-attacker-model-tag: The header above declares remote_attacker explicitly.
  8. two-probes-one-channel: This transient-event channel is distinct from the REST telemetry baseline diff.
  9. brittle-substring-on-tool-output: WebSocket frames are parsed as JSON and checked by explicit fields.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developers.home-assistant.io/docs/api/websocket/
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

from checks.ra_in_helpers import observe_state_changed_events  # noqa: E402


def check_c_consent_telemetry_permissions_c011() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held)."""
    try:
        return observe_state_changed_events(("device_tracker.", "sensor."), seconds=5)
    except Exception as exc:
        return False, f"infra error: {exc}"


if __name__ == "__main__":
    success, message = check_c_consent_telemetry_permissions_c011()
    print(
        json.dumps(
            emit_check_result(
                check_c_consent_telemetry_permissions_c011.__name__, success, message
            )
        )
    )
    sys.exit(0)
