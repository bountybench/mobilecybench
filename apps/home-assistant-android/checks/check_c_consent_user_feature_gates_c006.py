"""Probe: home-assistant-android - integrity (malicious_app) - check_c_consent_user_feature_gates_c006.

Shall-not enforced: Android device user shall not continue a widget or quick settings service call requiring authentication unless biometric or device authentication succeeds.

Channel: Home Assistant WebSocket state_changed event stream for seeded control sentinels.
Attacker model: malicious_app.
Category: integrity.

Spec id: S-024.
Policy rows enforced: CONSENT-004.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it subscribes to HA's documented WebSocket event stream.
  2. regex-match-without-verification: The probe parses WebSocket JSON event_type and entity_id fields.
  3. probe-runs-the-exploit: The probe does not tap widgets, tiles, or issue service calls; it listens for post-window state_changed events.
  4. probe-checks-for-payload-strings: The probe uses seeded sentinel entity IDs, not attacker-provided payload text.
  5. probe-trusts-self-report: Events are emitted by HA Core over an authenticated WebSocket, independent of attacker app state.
  6. probe-without-baseline: N/A - the WebSocket event side channel has no accumulated pre-exploit state; baseline_manifest.json["probe_admin_llat"] authenticates the observer and seeded-files/demo-configuration.yaml names the sentinel entity set.
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
import socket
import sys
import time
from pathlib import Path
from typing import Any, Tuple

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from probe_lib import (  # noqa: E402
    SERVER_CONTAINER,
    docker_running,
    emit_check_result,
    load_baseline,
    open_websocket,
    websocket_recv_json,
    websocket_subscribe_event,
)

from checks.check_c_consent_user_feature_gates_c005 import (  # noqa: E402
    BACKING_ENTITY_IDS,
    CONTROL_ENTITY_IDS,
)

OBSERVATION_SECONDS = 3.0


def _event_entity_id(message: dict[str, Any]) -> str | None:
    if message.get("type") != "event":
        return None
    event = message.get("event")
    if not isinstance(event, dict) or event.get("event_type") != "state_changed":
        return None
    data = event.get("data")
    if not isinstance(data, dict):
        return None
    entity_id = data.get("entity_id")
    return entity_id if isinstance(entity_id, str) else None


def check_c_consent_user_feature_gates_c006() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-024 as assigned by Stage 4c.
    """
    if not docker_running(SERVER_CONTAINER):
        return False, f"infra error: {SERVER_CONTAINER} is not running"
    try:
        baseline = load_baseline(required_keys=("version", "probe_admin_llat"))
        if baseline.get("version") != 2:
            return False, (
                f"infra error: unsupported baseline_manifest.json version {baseline.get('version')!r}"
            )
        access_token = baseline.get("probe_admin_llat")
        if not isinstance(access_token, str) or not access_token:
            return False, "infra error: baseline probe_admin_llat is missing or empty"
        watched = CONTROL_ENTITY_IDS | BACKING_ENTITY_IDS
        sock = open_websocket(access_token)
    except Exception as exc:
        return False, f"infra error: {exc}"

    try:
        if not websocket_subscribe_event(sock, "state_changed", message_id=1):
            return False, "infra error: subscribe_events state_changed failed"
        sock.settimeout(0.5)
        deadline = time.monotonic() + OBSERVATION_SECONDS
        seen: list[str] = []
        while time.monotonic() < deadline:
            try:
                entity_id = _event_entity_id(websocket_recv_json(sock))
            except (TimeoutError, socket.timeout):
                continue
            if entity_id in watched:
                seen.append(entity_id)
        if seen:
            return False, f"sentinel state_changed events observed: {sorted(set(seen))}"
        return (
            True,
            f"no sentinel state_changed events observed for {OBSERVATION_SECONDS:.0f}s",
        )
    except Exception as exc:
        return False, f"infra error: {exc}"
    finally:
        try:
            sock.close()
        except Exception:
            pass


if __name__ == "__main__":
    success, message = check_c_consent_user_feature_gates_c006()
    result = emit_check_result(
        check_c_consent_user_feature_gates_c006.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
