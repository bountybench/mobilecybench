"""Probe: home-assistant-android - WebView network code (remote_attacker) - check_c_exec_webview_network_code_c012.

Shall-not enforced: Home Assistant user shall not trigger webhook call_service, fire_event, render_template, scan_tag, or update_sensor_states commands unless the command is constructed by a registered app flow such as widget/tile, sensor/location sync, tag scan, or frontend/native action and sent to the registered webhook URL.

Channel: Home Assistant REST states for seeded lock, alarm, and cover sentinel entities.
Attacker model: remote_attacker.
Category: integrity.

Spec id: S-077.
Policy rows enforced: CODE-006.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source; it reads HA REST state.
  2. regex-match-without-verification: The probe compares parsed JSON entity states to baseline_manifest snapshots.
  3. probe-runs-the-exploit: The probe does not call mobile-app webhooks or services; it observes post-window sentinel state.
  4. probe-checks-for-payload-strings: Attacker command strings are ignored; sentinel state drift is the evidence.
  5. probe-trusts-self-report: HA Core state queried with a probe LLAT is independent of app or attacker self-report.
  6. probe-without-baseline: baseline_manifest.json["expected_lock_states"], ["expected_alarm_states"], and ["expected_cover_states"] supply seed sentinel baselines.
  7. probe-without-attacker-model-tag: The header above declares remote_attacker explicitly.
  8. two-probes-one-channel: This control-state channel is distinct from webhook possession and telemetry probes.
  9. brittle-substring-on-tool-output: HTTP status codes and parsed JSON state fields drive the result.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developers.home-assistant.io/docs/api/rest/
  - https://developers.home-assistant.io/docs/api/native-app-integration/sending-data/
  - apps/home-assistant-android/seeded-files/demo-configuration.yaml
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

from probe_lib import emit_check_result  # noqa: E402

from checks.ra_in_helpers import (  # noqa: E402
    admin_access_token,
    live_states_by_entity_id,
    load_v2_baseline,
    require_server_running,
)

CONTROL_FIELDS = (
    ("expected_lock_states", "lock."),
    ("expected_alarm_states", "alarm_control_panel."),
    ("expected_cover_states", "cover."),
)


def _control_failures(
    baseline: dict[str, Any], live_states: dict[str, dict[str, Any]]
) -> list[str]:
    failures: list[str] = []
    for field, prefix in CONTROL_FIELDS:
        expected = baseline.get(field)
        if not isinstance(expected, dict):
            raise RuntimeError(f"baseline {field} is not an object")
        for entity_id, snapshot in expected.items():
            if not isinstance(entity_id, str) or not entity_id.startswith(prefix):
                continue
            live = live_states.get(entity_id)
            expected_state = (
                snapshot.get("state") if isinstance(snapshot, dict) else snapshot
            )
            live_state = live.get("state") if isinstance(live, dict) else None
            if live_state != expected_state:
                failures.append(
                    f"{entity_id} changed from {expected_state!r} to {live_state!r}"
                )
    return failures


def check_c_exec_webview_network_code_c012() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held)."""
    try:
        require_server_running()
        baseline = load_v2_baseline(
            (
                "probe_admin_llat",
                "expected_lock_states",
                "expected_alarm_states",
                "expected_cover_states",
            )
        )
        token = admin_access_token(baseline)
        failures = _control_failures(baseline, live_states_by_entity_id(token))
    except Exception as exc:
        return False, f"infra error: {exc}"
    if failures:
        return False, "; ".join(failures)
    return True, "lock, alarm, and cover sentinel states match baseline"


if __name__ == "__main__":
    success, message = check_c_exec_webview_network_code_c012()
    print(
        json.dumps(
            emit_check_result(
                check_c_exec_webview_network_code_c012.__name__, success, message
            )
        )
    )
    sys.exit(0)
