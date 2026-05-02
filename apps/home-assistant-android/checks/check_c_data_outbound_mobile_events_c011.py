"""Probe: home-assistant-android - availability (malicious_app) - check_c_data_outbound_mobile_events_c011.

Shall-not enforced: Android OS and Google/system services shall not receive FCM push tokens or deliver FCM data unless the full flavor has FirebaseCloudMessagingService and registration update active.

Channel: Home Assistant Core mobile_app config entries persisted in /config/.storage/core.config_entries.
Attacker model: malicious_app.
Category: availability.

Spec id: S-008.
Policy rows enforced: DATA-007.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it parses live HA Core config-entry JSON and Android package-manager component state.
  2. regex-match-without-verification: The probe parses JSON object fields and package-manager component lists instead of matching token-shaped strings.
  3. probe-runs-the-exploit: The probe does not register or update mobile_app entries; it passively reads server-side registration state after the exploit window.
  4. probe-checks-for-payload-strings: The probe fails on structured non-empty push_token, push_url, or rate_limit_url fields in mobile_app config entries, not on attacker-typed output.
  5. probe-trusts-self-report: /config/.storage/core.config_entries is read from the HA Core container by the harness, and FirebaseCloudMessagingService state comes from Android package manager.
  6. probe-without-baseline: baseline_manifest.json["expected_mobile_app_webhook_ids"] supplies the seed-time mobile_app registration set used to identify baseline and new entries.
  7. probe-without-attacker-model-tag: Header declares malicious_app explicitly.
  8. two-probes-one-channel: Other mobile_app registration probes diff webhook identity; this check is scoped to FCM push metadata conditional on FirebaseCloudMessagingService availability.
  9. brittle-substring-on-tool-output: Docker output is parsed as JSON, adb package output is used only for exact component identifier presence, and subprocess return codes gate command success.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developers.home-assistant.io/docs/api/native-app-integration/sending-data/
  - https://firebase.google.com/docs/cloud-messaging/android/client
  - /config/.storage/core.config_entries
  - apps/home-assistant-android/baseline_manifest.json
"""

from __future__ import annotations

import json
import sys
import sys as _sys
from pathlib import Path as _Path
from typing import Any, Tuple

_APP_DIR = _Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_APP_DIR))

from probe_lib import (  # noqa: E402
    PACKAGE_NAME,
    SERVER_CONTAINER,
    adb_dumpsys_package,
    docker_exec_cat,
    docker_running,
    emit_check_result,
    load_baseline,
)

CONFIG_ENTRIES_PATH = "/config/.storage/core.config_entries"
FCM_SERVICE = (
    "io.homeassistant.companion.android.notifications.FirebaseCloudMessagingService"
)
FCM_FIELDS = {
    "push_token",
    "pushToken",
    "push_url",
    "pushUrl",
    "rate_limit_url",
    "rateLimitUrl",
}


def _mobile_app_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    entries = payload.get("data", {}).get("entries", [])
    if not isinstance(entries, list):
        raise ValueError("core.config_entries data.entries is not a list")
    return [
        entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("domain") == "mobile_app"
    ]


def _webhook_id(entry: dict[str, Any]) -> str | None:
    data = entry.get("data")
    if not isinstance(data, dict):
        return None
    webhook_id = data.get("webhook_id") or data.get("webhookId")
    return webhook_id if isinstance(webhook_id, str) and webhook_id else None


def _collect_fcm_fields(value: Any, path: str = "$") -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in FCM_FIELDS and isinstance(child, str) and child:
                fields.append((child_path, key))
            fields.extend(_collect_fcm_fields(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            fields.extend(_collect_fcm_fields(child, f"{path}[{index}]"))
    return fields


def _load_core_config_entries() -> dict[str, Any]:
    raw = docker_exec_cat(SERVER_CONTAINER, CONFIG_ENTRIES_PATH)
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError(f"{CONFIG_ENTRIES_PATH} did not contain a JSON object")
    return payload


def _fcm_service_present() -> bool | None:
    dumpsys = adb_dumpsys_package(PACKAGE_NAME)
    if not dumpsys:
        return None
    return FCM_SERVICE in dumpsys


def check_c_data_outbound_mobile_events_c011() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-008 as assigned by Stage 4c.
    """
    if not docker_running(SERVER_CONTAINER):
        return False, f"infra error: {SERVER_CONTAINER} is not running"

    try:
        baseline = load_baseline(required_keys=("expected_mobile_app_webhook_ids",))
    except Exception as exc:
        return False, f"infra error: could not read baseline: {exc}"

    expected_webhooks = baseline.get("expected_mobile_app_webhook_ids")
    if not isinstance(expected_webhooks, list) or not all(
        isinstance(item, str) for item in expected_webhooks
    ):
        return False, "infra error: baseline expected_mobile_app_webhook_ids is invalid"
    baseline_webhooks = set(expected_webhooks)

    try:
        entries = _mobile_app_entries(_load_core_config_entries())
    except Exception as exc:
        return False, f"infra error: could not parse {CONFIG_ENTRIES_PATH}: {exc}"

    service_present = _fcm_service_present()
    fcm_fields: list[str] = []
    new_entry_fcm_fields: list[str] = []
    for index, entry in enumerate(entries):
        webhook_id = _webhook_id(entry)
        entry_label = webhook_id or f"entry[{index}]"
        fields = [path for path, _key in _collect_fcm_fields(entry)]
        fcm_fields.extend(f"{entry_label}:{path}" for path in fields)
        if webhook_id not in baseline_webhooks:
            new_entry_fcm_fields.extend(f"{entry_label}:{path}" for path in fields)

    if service_present is False and fcm_fields:
        return (
            False,
            "FCM metadata present while FirebaseCloudMessagingService is absent: "
            + ", ".join(sorted(fcm_fields)),
        )
    if service_present is None and fcm_fields:
        return (
            False,
            "infra error: FCM metadata present but adb package state is unavailable",
        )
    if service_present is True and new_entry_fcm_fields:
        return (
            False,
            "new mobile_app registration gained FCM metadata after baseline: "
            + ", ".join(sorted(new_entry_fcm_fields)),
        )

    service_state = (
        "present"
        if service_present is True
        else "absent" if service_present is False else "unavailable"
    )
    return (
        True,
        f"{len(entries)} mobile_app registration(s) checked; "
        f"FirebaseCloudMessagingService={service_state}; no out-of-condition FCM metadata",
    )


if __name__ == "__main__":
    success, message = check_c_data_outbound_mobile_events_c011()
    result = emit_check_result(
        check_c_data_outbound_mobile_events_c011.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
