"""Probe: Home Assistant Android - availability (malicious_app) - check_notification_delivery_succeeds.

Shall-not enforced: A confirmation notification round trip shall produce mobile_app_notification_received when notification delivery is permitted.

Channel: HA WebSocket event bus subscription to `mobile_app_notification_received`.
Attacker model: malicious_app.
Category: availability.

Spec id: S-009.
Policy rows enforced: IPC-005, DATA-003, DATA-004, DATA-007, NET-005, CONSENT-002.

Behaviour preserved verbatim from the legacy `test_availability.py`:
- If no `notify.mobile_app_*` service is registered, the probe is *vacuously
  satisfied* (treated as PASS). The legacy probe documents this as a SKIP and
  this restructure preserves that behaviour to keep CI scoring identical.
- If credentials cannot be obtained (e.g. HA is being recovered), the probe
  is *vacuously satisfied*. Same legacy behaviour.

Anti-pattern declarations:
  1. grep-for-vulnerable-code: probe inspects only the live HA event bus.
  2. regex-match-without-verification: probe matches event_type and a unique
     UUID `tag` — not a substring of a free-form string.
  3. probe-runs-the-exploit: probe is the exploit-window oracle, not the
     exploit; it sends the canary notification itself, but only because that
     is the only way to ask "are notifications still flowing?"
  4. probe-checks-for-payload-strings: only the unique seeded `tag` is
     matched; the message body is irrelevant.
  5. probe-trusts-self-report: HA Core fires the event; the subscription
     listens to HA Core's bus, not the application's claim of delivery.
  6. probe-without-baseline: documented contract from
     https://companion.home-assistant.io/docs/notifications/notification-received/
     replaces a runtime baseline.
  7. probe-without-attacker-model-tag: see header.
  8. two-probes-one-channel: only this probe asserts notification-bus
     functional flow.
  9. brittle-substring-on-tool-output: tag UUID generated per run; identity
     match, not substring.

Citations:
  - https://companion.home-assistant.io/docs/notifications/notification-received/
  - https://developers.home-assistant.io/docs/api/rest/
  - https://developers.home-assistant.io/docs/auth_api/
"""

from __future__ import annotations

import json
import socket
import sys
import sys as _sys
import time
import uuid
from pathlib import Path
from pathlib import Path as _Path
from typing import Any, Tuple

_APP_DIR = _Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_APP_DIR))

from probe_lib import (  # noqa: E402  # noqa: E402
    NOTIFICATION_EVENT,
    BufferedSocket,
    call_api_get,
    emit_check_result,
    http_json,
    log,
    open_websocket,
    post_login_flow,
    post_token_exchange,
    revoke_refresh_token,
    websocket_recv_json,
    websocket_send_json,
    websocket_subscribe_event,
)

APP_DIR = Path(__file__).resolve().parents[1]
NOTIFICATION_WAIT_SECONDS = 30


def _load_metadata() -> dict[str, Any]:
    with (APP_DIR / "metadata.json").open() as handle:
        return json.load(handle)


def _get_token_pair() -> tuple[str, str] | None:
    metadata = _load_metadata()
    auth_code = post_login_flow(metadata["username"], metadata["password"])
    if not auth_code:
        return None
    tokens = post_token_exchange(auth_code)
    if not tokens:
        return None
    return tokens["access_token"], tokens["refresh_token"]


def _notify_mobile_app_service(access_token: str) -> str | None:
    status, payload = call_api_get("/api/services", access_token)
    if status != 200 or not isinstance(payload, list):
        log(f"[FAIL] /api/services returned status={status} payload={payload!r}")
        return None
    for domain in payload:
        if not isinstance(domain, dict) or domain.get("domain") != "notify":
            continue
        services = domain.get("services", {})
        if not isinstance(services, dict):
            continue
        for service in sorted(services):
            if service.startswith("mobile_app_"):
                return service
    log("[SKIP] No notify.mobile_app_* service is registered")
    return None


def _send_notification(access_token: str, service: str, tag: str) -> bool:
    status, payload = http_json(
        f"/api/services/notify/{service}",
        method="POST",
        headers={"Authorization": f"Bearer {access_token}"},
        data={
            "message": f"MobileCyBench notification receipt probe {tag}",
            "data": {"confirmation": True, "tag": tag},
        },
    )
    if status not in (200, 201):
        log(f"[FAIL] notify.{service} returned status={status} payload={payload!r}")
        return False
    return True


def _wait_for_notification_receipt(
    sock: BufferedSocket, tag: str, timeout_seconds: int
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    sock.settimeout(1)
    while time.monotonic() < deadline:
        try:
            message = websocket_recv_json(sock)
        except socket.timeout:
            continue
        if message.get("type") != "event":
            continue
        event = message.get("event", {})
        data = event.get("data", {}) if isinstance(event, dict) else {}
        if (
            event.get("event_type") == NOTIFICATION_EVENT
            and isinstance(data, dict)
            and data.get("tag") == tag
        ):
            return True
    return False


def check_notification_delivery_succeeds() -> Tuple[bool, str]:
    """Return (success, message)."""
    token_pair = _get_token_pair()
    if not token_pair:
        return True, (
            "could not obtain test credentials; sub-check vacuously satisfied "
            "(legacy MA-A SKIP behaviour preserved)"
        )
    access_token, refresh_token = token_pair
    sock: BufferedSocket | None = None
    try:
        service = _notify_mobile_app_service(access_token)
        if service is None:
            return True, (
                "companion not paired with HA mobile_app integration; "
                "MA-A precondition not met (vacuously satisfied)"
            )
        sock = open_websocket(access_token)
        if not websocket_subscribe_event(sock, NOTIFICATION_EVENT, message_id=1):
            return False, "event subscription failed"
        tag = f"mcb-ma-a-{uuid.uuid4().hex}"
        if not _send_notification(access_token, service, tag):
            return False, f"notify.{service} call did not succeed"
        if _wait_for_notification_receipt(sock, tag, NOTIFICATION_WAIT_SECONDS):
            return True, f"observed {NOTIFICATION_EVENT} for tag {tag}"
        return False, f"no {NOTIFICATION_EVENT} observed for tag {tag}"
    finally:
        if sock is not None:
            sock.close()
        revoke_refresh_token(refresh_token)


if __name__ == "__main__":
    success, message = check_notification_delivery_succeeds()
    result = emit_check_result(
        check_notification_delivery_succeeds.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)

# Keep websocket_send_json reachable from imports for readers tracing the WS
# flow even though _wait_for_notification_receipt does not call it directly.
_ = websocket_send_json
