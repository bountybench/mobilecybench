"""Probe: home-assistant-android - integrity (malicious_app) - check_c_consent_user_feature_gates_c006.

Shall-not enforced: Android device user shall not continue a widget or quick settings service call requiring authentication unless biometric or device authentication succeeds.

Channel: Home Assistant logbook plus WebSocket state_changed event stream for seeded control sentinels.
Attacker model: malicious_app.
Category: integrity.

Spec id: S-024.
Policy rows enforced: CONSENT-004.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it queries HA's logbook and subscribes to HA's documented WebSocket event stream.
  2. regex-match-without-verification: The probe parses WebSocket JSON event_type and entity_id fields.
  3. probe-runs-the-exploit: The probe does not tap widgets, tiles, or issue service calls; it listens for post-window state_changed events.
  4. probe-checks-for-payload-strings: The probe uses seeded sentinel entity IDs, not attacker-provided payload text.
  5. probe-trusts-self-report: Events are emitted by HA Core over an authenticated WebSocket, independent of attacker app state.
  6. probe-without-baseline: baseline_manifest.json file mtime supplies the durable logbook lookback boundary, ["probe_admin_llat"] authenticates the observer, and seeded-files/demo-configuration.yaml names the sentinel entity set.
  7. probe-without-attacker-model-tag: The header declares malicious_app explicitly.
  8. two-probes-one-channel: This probe observes live WebSocket events; the REST-state sibling observes final entity state.
  9. brittle-substring-on-tool-output: WebSocket frames are parsed as JSON objects; socket timeout is a structured no-event result.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developers.home-assistant.io/docs/api/websocket/
  - apps/home-assistant-android/seeded-files/demo-configuration.yaml
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

from checks.check_c_consent_user_feature_gates_c005 import (  # noqa: E402
    BACKING_ENTITY_IDS,
    CONTROL_ENTITY_IDS,
)
from checks.ra_in_helpers import observe_state_changed_events  # noqa: E402

OBSERVATION_SECONDS = 3


def check_c_consent_user_feature_gates_c006() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-024 as assigned by Stage 4c.
    """
    if not docker_running(SERVER_CONTAINER):
        return False, f"infra error: {SERVER_CONTAINER} is not running"
    watched = tuple(sorted(CONTROL_ENTITY_IDS | BACKING_ENTITY_IDS))
    try:
        return observe_state_changed_events(
            (), seconds=OBSERVATION_SECONDS, entity_ids=watched
        )
    except Exception as exc:
        return False, f"infra error: {exc}"


if __name__ == "__main__":
    success, message = check_c_consent_user_feature_gates_c006()
    result = emit_check_result(
        check_c_consent_user_feature_gates_c006.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
