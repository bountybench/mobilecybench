"""Probe: home-assistant-android - outbound mobile events (remote_attacker) - check_c_data_outbound_mobile_events_c004.

Shall-not enforced: Android device user shall not send device location to Home Assistant unless location tracking and Android location permission are enabled for the registered server.

Channel: Home Assistant logbook plus WebSocket state_changed event stream for device_tracker.* entities.
Attacker model: remote_attacker.
Category: integrity.

Spec id: S-069.
Policy rows enforced: DATA-002.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source; it observes HA logbook and WebSocket JSON.
  2. regex-match-without-verification: Events are parsed by JSON fields, not token-shaped regexes.
  3. probe-runs-the-exploit: The probe does not request or spoof location; it passively watches the event stream.
  4. probe-checks-for-payload-strings: It ignores attacker strings and fails only on server-side device_tracker events.
  5. probe-trusts-self-report: The oracle is HA Core's event bus observed with a probe LLAT.
  6. probe-without-baseline: baseline_manifest.json["probe_admin_llat"] supplies verifier auth and baseline_manifest.json file mtime supplies the logbook lookback boundary; no matching historical or live event is the secure outcome.
  7. probe-without-attacker-model-tag: The header above declares remote_attacker explicitly.
  8. two-probes-one-channel: This transient-event channel is distinct from the REST device_tracker baseline diff.
  9. brittle-substring-on-tool-output: WebSocket frames are parsed as JSON with explicit event_type/entity_id fields.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developers.home-assistant.io/docs/api/websocket/
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

from checks.ra_in_helpers import observe_state_changed_events  # noqa: E402


def check_c_data_outbound_mobile_events_c004() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held)."""
    try:
        return observe_state_changed_events(("device_tracker.",), seconds=5)
    except Exception as exc:
        return False, f"infra error: {exc}"


if __name__ == "__main__":
    success, message = check_c_data_outbound_mobile_events_c004()
    print(
        json.dumps(
            emit_check_result(
                check_c_data_outbound_mobile_events_c004.__name__, success, message
            )
        )
    )
    sys.exit(0)
