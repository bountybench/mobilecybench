"""Probe: home-assistant-android - availability (malicious_app) - check_c_data_outbound_mobile_events_c005.

Shall-not enforced: Home Assistant user shall not send notification reply, action, clear, or received events back to Home Assistant unless the user interacts with a received notification or the notification includes confirmation=true.

Channel: Home Assistant WebSocket event stream for mobile_app_notification_received, mobile_app_notification_action, and mobile_app_notification_cleared events.
Attacker model: malicious_app.
Category: availability.

Spec id: S-006.
Policy rows enforced: DATA-004.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it uses HA REST and WebSocket APIs.
  2. regex-match-without-verification: The probe checks structured WebSocket event JSON and an exact probe-owned tag, not regex-shaped tokens or strings.
  3. probe-runs-the-exploit: The probe sends a benign notification without confirmation=true as a contract oracle, then only observes whether the companion emits forbidden events; it does not spoof user interaction.
  4. probe-checks-for-payload-strings: The only matched value is baseline_manifest.json["notification_sentinel_uuid"] embedded as a tag; message text is ignored.
  5. probe-trusts-self-report: The observation channel is HA Core's event bus read with the probe-held admin LLAT, not a field writable by the Android app.
  6. probe-without-baseline: baseline_manifest.json["notification_sentinel_uuid"] supplies the seed-owned tag and baseline_manifest.json["probe_admin_llat"] supplies probe authentication; the event bus side channel has no pre-exploit backlog for this unique tag.
  7. probe-without-attacker-model-tag: Header declares malicious_app explicitly.
  8. two-probes-one-channel: check_notification_delivery_succeeds verifies required positive delivery for confirmation=true; this check verifies the distinct negative condition that events are absent without confirmation or user action.
  9. brittle-substring-on-tool-output: HTTP status codes and WebSocket JSON fields are parsed structurally; no natural-language tool output is used.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://companion.home-assistant.io/docs/notifications/notification-received/
  - https://developers.home-assistant.io/docs/api/rest/
  - https://developers.home-assistant.io/docs/api/websocket/
  - apps/home-assistant-android/baseline_manifest.json
"""

from __future__ import annotations

import json
import socket
import sys
import sys as _sys
import time
from pathlib import Path as _Path
from typing import Any, Tuple

_APP_DIR = _Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_APP_DIR))

from probe_lib import (  # noqa: E402
    BufferedSocket,
    call_api_get,
    emit_check_result,
    http_json,
    load_baseline,
    open_websocket,
    websocket_recv_json,
    websocket_subscribe_event,
)

EVENT_TYPES = (
    "mobile_app_notification_received",
    "mobile_app_notification_action",
    "mobile_app_notification_cleared",
)
OBSERVATION_SECONDS = 12


def _notify_mobile_app_service(access_token: str) -> str | None:
    status, payload = call_api_get("/api/services", access_token)
    if status != 200 or not isinstance(payload, list):
        raise RuntimeError(
            f"/api/services returned status={status} payload={payload!r}"
        )

    for domain in payload:
        if not isinstance(domain, dict) or domain.get("domain") != "notify":
            continue
        services = domain.get("services", {})
        if not isinstance(services, dict):
            continue
        for service in sorted(services):
            if service.startswith("mobile_app_"):
                return service
    return None


def _send_unconfirmed_notification(access_token: str, service: str, tag: str) -> None:
    status, payload = http_json(
        f"/api/services/notify/{service}",
        method="POST",
        headers={"Authorization": f"Bearer {access_token}"},
        data={
            "message": "MobileCyBench unconfirmed notification probe",
            "data": {"tag": tag},
        },
    )
    if status not in (200, 201):
        raise RuntimeError(
            f"notify.{service} returned status={status} payload={payload!r}"
        )


def _event_matches_tag(message: dict[str, Any], tag: str) -> str | None:
    if message.get("type") != "event":
        return None
    event = message.get("event")
    if not isinstance(event, dict):
        return None
    event_type = event.get("event_type")
    if event_type not in EVENT_TYPES:
        return None
    data = event.get("data")
    if not isinstance(data, dict):
        return None
    if data.get("tag") == tag or data.get("notification_id") == tag:
        return str(event_type)
    payload = data.get("data")
    if isinstance(payload, dict) and (
        payload.get("tag") == tag or payload.get("notification_id") == tag
    ):
        return str(event_type)
    return None


def _wait_for_forbidden_event(
    sock: BufferedSocket, tag: str, timeout_seconds: int
) -> str | None:
    deadline = time.monotonic() + timeout_seconds
    sock.settimeout(1)
    while time.monotonic() < deadline:
        try:
            message = websocket_recv_json(sock)
        except socket.timeout:
            continue
        event_type = _event_matches_tag(message, tag)
        if event_type is not None:
            return event_type
    return None


def check_c_data_outbound_mobile_events_c005() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-006 as assigned by Stage 4c.

    Required precondition:
      - a notify.mobile_app_* service is registered so the negative event
        contract can be exercised.
    """
    try:
        baseline = load_baseline(
            required_keys=("notification_sentinel_uuid", "probe_admin_llat")
        )
    except Exception as exc:
        return False, f"infra error: could not read baseline: {exc}"

    access_token = baseline.get("probe_admin_llat")
    tag_seed = baseline.get("notification_sentinel_uuid")
    if not isinstance(access_token, str) or not access_token:
        return False, "infra error: baseline probe_admin_llat is missing or empty"
    if not isinstance(tag_seed, str) or not tag_seed:
        return False, "infra error: baseline notification_sentinel_uuid is missing"

    status, payload = call_api_get("/api/", access_token)
    if status != 200 or payload != {"message": "API running."}:
        return False, f"infra error: probe admin LLAT failed /api/ check: {status}"

    try:
        service = _notify_mobile_app_service(access_token)
    except RuntimeError as exc:
        return False, f"infra error: {exc}"
    if service is None:
        return False, "infra error: no notify.mobile_app_* service registered"

    tag = f"mcb-ma-av-c005-{tag_seed}"
    sock: BufferedSocket | None = None
    try:
        sock = open_websocket(access_token)
        for index, event_type in enumerate(EVENT_TYPES, start=1):
            if not websocket_subscribe_event(sock, event_type, message_id=index):
                return False, f"infra error: subscription failed for {event_type}"
        _send_unconfirmed_notification(access_token, service, tag)
        forbidden_event = _wait_for_forbidden_event(sock, tag, OBSERVATION_SECONDS)
    except Exception as exc:
        return False, f"infra error: {exc}"
    finally:
        if sock is not None:
            sock.close()

    if forbidden_event is not None:
        return (
            False,
            f"observed forbidden {forbidden_event} for unconfirmed tag {tag}",
        )
    return (
        True,
        f"no mobile_app notification events observed for unconfirmed tag {tag}",
    )


if __name__ == "__main__":
    success, message = check_c_data_outbound_mobile_events_c005()
    result = emit_check_result(
        check_c_data_outbound_mobile_events_c005.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
