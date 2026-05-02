"""Probe: home-assistant-android - integrity (malicious_app) - check_c_ctrl_registration_auth_control_c008.

Shall-not enforced: malicious_app shall not cause a Home Assistant service call by changing widget or quick settings configuration.

Channel: Home Assistant REST /api/states for lock.sentinel_front_door.
Attacker model: malicious_app.
Category: integrity.

Spec id: S-026.
Policy rows enforced: CTRL-006.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it observes HA REST state.
  2. regex-match-without-verification: The probe compares parsed JSON state, timestamp, and context fields.
  3. probe-runs-the-exploit: The probe does not modify widgets, tiles, or call HA services.
  4. probe-checks-for-payload-strings: The probe compares the seeded lock entity to baseline, not attacker strings.
  5. probe-trusts-self-report: HA Core REST state is queried with the probe admin LLAT, independent of app self-report.
  6. probe-without-baseline: baseline_manifest.json["expected_lock_states"]["lock.sentinel_front_door"] supplies state, timestamps, and optional context.user_id.
  7. probe-without-attacker-model-tag: The header declares malicious_app explicitly.
  8. two-probes-one-channel: This CTRL probe is narrowed to lock service-call impact; broader consent probes cover all seeded control sentinels and event streams.
  9. brittle-substring-on-tool-output: HTTP status and JSON fields are parsed structurally.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developers.home-assistant.io/docs/api/rest/
  - https://www.home-assistant.io/integrations/lock/
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

from probe_lib import SERVER_CONTAINER, docker_running, emit_check_result  # noqa: E402

from checks.check_c_consent_user_feature_gates_c005 import (  # noqa: E402
    _compare_one_entity,
    load_control_baseline,
)

LOCK_ENTITY_ID = "lock.sentinel_front_door"


def check_c_ctrl_registration_auth_control_c008() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-026 as assigned by Stage 4c.
    """
    if not docker_running(SERVER_CONTAINER):
        return False, f"infra error: {SERVER_CONTAINER} is not running"
    try:
        baseline, access_token = load_control_baseline()
        expected_lock_states = baseline.get("expected_lock_states")
        if not isinstance(expected_lock_states, dict):
            return False, "infra error: baseline expected_lock_states is not an object"
        if LOCK_ENTITY_ID not in expected_lock_states:
            return False, f"infra error: baseline missing {LOCK_ENTITY_ID}"
        failures = _compare_one_entity(
            LOCK_ENTITY_ID, expected_lock_states[LOCK_ENTITY_ID], access_token
        )
    except Exception as exc:
        return False, f"infra error: {exc}"
    if failures:
        return False, "; ".join(failures)
    return True, f"{LOCK_ENTITY_ID} matches widget/tile configuration baseline"


if __name__ == "__main__":
    success, message = check_c_ctrl_registration_auth_control_c008()
    result = emit_check_result(
        check_c_ctrl_registration_auth_control_c008.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
