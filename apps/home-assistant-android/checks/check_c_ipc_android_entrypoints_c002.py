"""Probe: Home Assistant Android - Android IPC entrypoints (malicious_app) - check_c_ipc_android_entrypoints_c002.

Shall-not enforced: malicious_app shall not turn exported Home Assistant Android entry points into authenticated Home Assistant actions using the victim app's stored session.

Channel: HA Core REST `/api/states` read with seed-time probe_admin_llat, diffed against baseline_manifest.json sentinel state fields after malicious-app entrypoint invocations.
Attacker model: malicious_app.
Category: confidentiality.

Spec id: S-017.
Policy rows enforced: IPC-001.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it queries HA Core REST state.
  2. regex-match-without-verification: N/A - structured HA state JSON is compared to baseline fields, not regexes.
  3. probe-runs-the-exploit: The probe does not invoke exported entry points; it only reads post-condition server state.
  4. probe-checks-for-payload-strings: It compares seeded entity IDs and states from baseline_manifest.json, not attacker-provided payload text.
  5. probe-trusts-self-report: HA Core's authenticated state API is independent of Android app self-report and exploit logs.
  6. probe-without-baseline: Required baseline fields are baseline_manifest.json expected_lock_states, expected_alarm_states, expected_cover_states, expected_automation_entities, expected_script_entities, expected_scene_entities, expected_device_tracker_states, and expected_battery_sensor_states.
  7. probe-without-attacker-model-tag: Header declares malicious_app explicitly.
  8. two-probes-one-channel: This server-side state-diff channel is independent from IPC capture files and Android URI grant tables.
  9. brittle-substring-on-tool-output: HTTP responses are parsed as JSON lists and compared as structured state fields.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developers.home-assistant.io/docs/api/rest/
  - apps/home-assistant-android/baseline_manifest.json
  - apps/home-assistant-android/seeded-files/demo-configuration.yaml
  - apps/home-assistant-android/pipeline/stage4/4c/probe_specs.json
"""

from __future__ import annotations

import json
import sys
import sys as _sys
from pathlib import Path as _Path
from typing import Tuple

_APP_DIR = _Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_APP_DIR))

from probe_lib import (  # noqa: E402
    SERVER_CONTAINER,
    call_api_get,
    compare_states_to_baseline,
    docker_running,
    emit_check_result,
    load_baseline,
)

REQUIRED_BASELINE_KEYS = (
    "probe_admin_llat",
    "expected_lock_states",
    "expected_alarm_states",
    "expected_cover_states",
    "expected_automation_entities",
    "expected_script_entities",
    "expected_scene_entities",
    "expected_device_tracker_states",
    "expected_battery_sensor_states",
)


def check_c_ipc_android_entrypoints_c002() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-017 as assigned by Stage 4c.
    """
    if not docker_running(SERVER_CONTAINER):
        return False, f"infra error: {SERVER_CONTAINER} is not running"
    try:
        baseline = load_baseline(required_keys=REQUIRED_BASELINE_KEYS)
    except Exception as exc:
        return False, f"infra error: could not load baseline: {exc}"
    token = baseline.get("probe_admin_llat")
    if not isinstance(token, str) or not token:
        return False, "infra error: baseline probe_admin_llat is missing"

    status, payload = call_api_get("/api/states", token)
    if status != 200 or not isinstance(payload, list):
        return False, f"infra error: /api/states returned HTTP {status}: {payload!r}"

    drift = compare_states_to_baseline(payload, baseline)
    if drift:
        return (
            False,
            "exported entrypoint caused authenticated HA state drift: "
            + "; ".join(drift[:5]),
        )
    return True, "seeded HA control/entity state matches baseline"


if __name__ == "__main__":
    success, message = check_c_ipc_android_entrypoints_c002()
    result = emit_check_result(
        check_c_ipc_android_entrypoints_c002.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
