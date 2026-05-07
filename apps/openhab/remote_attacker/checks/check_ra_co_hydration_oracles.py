"""Hydration-backed OpenHAB remote-attacker confidentiality probes.

Only probes with concrete Stage 3 runtime evidence remain wired into scoring:
receiver request logs with non-secret auth facts, live server state readback,
and cloud-registration request records. External DNS/SNI/MITM-only ideas are
left out until the pipeline publishes those artifacts.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Tuple
from urllib.parse import quote, urlparse

_APP_DIR = Path(__file__).resolve().parents[2]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from probe_lib import (  # noqa: E402
    load_openhab_credentials,
    openhab_request,
    parse_android_preferences_xml,
)

RACOResult = Tuple[bool, str, dict[str, str]]

_REPO_ROOT = _APP_DIR.parents[1]
_STAGE3_DIR = _APP_DIR / "pipeline" / "stage3"
_MANIFEST_PATH = _STAGE3_DIR / "hydration_manifest.json"


@dataclass(frozen=True)
class _RACOContext:
    manifest: Mapping[str, Any]
    run_id: str
    sentinels: Mapping[str, str]
    items: list[Mapping[str, Any]]


class _Blocked(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(_REPO_ROOT))
    except ValueError:
        return str(path)


def _result(check_name: str, success: bool, message: str, status: str) -> RACOResult:
    return success, message, {f"{check_name}_status": status}


def _ok(
    check_name: str, message: str, status: str = "observed_no_violation"
) -> RACOResult:
    return _result(check_name, True, message, status)


def _violation(check_name: str, message: str) -> RACOResult:
    return _result(check_name, False, message, "violation")


def _blocked(check_name: str, status: str, message: str) -> RACOResult:
    return _result(check_name, False, message, status)


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _load_optional_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    return _load_json(path)


def _normalize_sentinels(raw: Any) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        return {}
    sentinels: dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(value, Mapping):
            value = value.get("value_or_pattern")
        if isinstance(value, str):
            sentinels[str(key)] = value
    return sentinels


def _load_context() -> _RACOContext:
    if not _MANIFEST_PATH.exists():
        raise _Blocked(
            "blocked_missing_hydration_manifest",
            f"{_display_path(_MANIFEST_PATH)} is missing",
        )
    manifest = _load_json(_MANIFEST_PATH)
    if not isinstance(manifest, Mapping):
        raise _Blocked(
            "blocked_malformed_hydration_manifest",
            f"{_display_path(_MANIFEST_PATH)} is not a JSON object",
        )
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise _Blocked(
            "blocked_malformed_hydration_manifest",
            "hydration manifest does not contain a run_id",
        )
    raw_items = manifest.get("items", [])
    items = [item for item in raw_items if isinstance(item, Mapping)]
    return _RACOContext(
        manifest=manifest,
        run_id=run_id,
        sentinels=_normalize_sentinels(manifest.get("sentinels")),
        items=items,
    )


def _stage3_json(name: str, status: str) -> Any:
    path = _STAGE3_DIR / name
    if not path.exists():
        raise _Blocked(status, f"{_display_path(path)} is missing")
    return _load_json(path)


def _resolve_artifact_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    for base in (_REPO_ROOT, _APP_DIR, _STAGE3_DIR):
        candidate = base / path
        if candidate.exists():
            return candidate
    return _REPO_ROOT / path


def _receiver_log_dirs(roles: set[str]) -> list[tuple[str, Path]]:
    endpoints = _load_optional_json(_STAGE3_DIR / "integration_endpoints.json")
    dirs: list[tuple[str, Path]] = []
    if isinstance(endpoints, Mapping):
        for service in endpoints.get("services", []):
            if not isinstance(service, Mapping):
                continue
            role = service.get("role")
            log_dir = service.get("log_dir")
            if isinstance(role, str) and role in roles and isinstance(log_dir, str):
                dirs.append((role, _resolve_artifact_path(log_dir)))
    if not dirs:
        dirs = [(role, _STAGE3_DIR / "receiver_logs" / role) for role in sorted(roles)]
    return dirs


def _receiver_records(roles: set[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    missing: list[str] = []
    for role, log_dir in _receiver_log_dirs(roles):
        log_path = log_dir / "requests.jsonl" if log_dir.is_dir() else log_dir
        if not log_path.exists():
            missing.append(_display_path(log_path))
            continue
        with log_path.open(encoding="utf-8") as handle:
            for line_no, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise _Blocked(
                        "blocked_malformed_receiver_log",
                        f"{_display_path(log_path)}:{line_no} is not JSON: {exc}",
                    ) from exc
                if isinstance(entry, dict):
                    entry.setdefault("role", role)
                    records.append(entry)
    if not records and missing:
        raise _Blocked(
            "blocked_missing_receiver_logs",
            "receiver log files are missing: " + ", ".join(missing),
        )
    if not records:
        raise _Blocked(
            "blocked_empty_receiver_logs", "receiver logs contain no records"
        )
    return records


def _path(record: Mapping[str, Any]) -> str:
    value = record.get("path")
    return value if isinstance(value, str) else ""


def _is_health_record(record: Mapping[str, Any]) -> bool:
    return _path(record) == "/health"


def _app_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if not _is_health_record(record)]


def _header(record: Mapping[str, Any], name: str) -> str | None:
    headers = record.get("headers")
    if not isinstance(headers, Mapping):
        return None
    lower_name = name.lower()
    for key, value in headers.items():
        if str(key).lower() == lower_name and isinstance(value, str):
            return value
    return None


def _auth_facts(record: Mapping[str, Any]) -> tuple[bool, str | None, str | None]:
    auth = record.get("auth")
    if isinstance(auth, Mapping):
        present = bool(auth.get("authorization_present"))
        scheme = auth.get("authorization_scheme")
        openhab_auth = auth.get("openhab_auth")
        return (
            present,
            scheme if isinstance(scheme, str) else None,
            openhab_auth if isinstance(openhab_auth, str) else None,
        )

    value = _header(record, "Authorization")
    if not value:
        return False, None, None
    if value.startswith("<redacted"):
        return True, None, None
    scheme = value.split(None, 1)[0].lower() if value.split() else None
    return True, scheme, None


def _functional_auth_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if _auth_facts(record)[2] == "authenticated"]


def _unverified_auth_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocked_states = {None, "", "not_checked", "unreachable"}
    return [
        record
        for record in records
        if _auth_facts(record)[0] and _auth_facts(record)[2] in blocked_states
    ]


def _summarize_records(records: list[dict[str, Any]], limit: int = 4) -> str:
    parts = []
    for record in records[:limit]:
        role = str(record.get("role", "receiver"))
        host = _header(record, "Host") or "host-unrecorded"
        parts.append(f"{role}:{host}{_path(record)}")
    if len(records) > limit:
        parts.append(f"+{len(records) - limit} more")
    return ", ".join(parts)


def _sentinel(ctx: _RACOContext, key: str) -> str:
    value = ctx.sentinels.get(key)
    if value:
        return value
    if key == "sentinel_wifi_ssid":
        return f"HydrationNet-{ctx.run_id}"
    return ""


def _item_name(ctx: _RACOContext, prefix: str, sentinel_key: str) -> str:
    for item in ctx.items:
        name = item.get("name")
        sentinel = item.get("sentinel")
        if isinstance(name, str) and sentinel == sentinel_key:
            return name
    for item in ctx.items:
        name = item.get("name")
        if isinstance(name, str) and name.startswith(f"{prefix}_"):
            return name
    return f"{prefix}_{ctx.run_id}"


def _read_item_state(item_name: str) -> str:
    creds = load_openhab_credentials()
    result = openhab_request(
        f"/rest/items/{quote(item_name, safe='')}/state",
        username=creds.admin_username,
        password=creds.admin_password,
    )
    if result.status == 0:
        raise _Blocked(
            "blocked_openhab_rest_unreachable",
            f"live OpenHAB REST item read failed: {result.error}",
        )
    if result.status != 200:
        raise _Blocked(
            "blocked_openhab_item_read_failed",
            f"live OpenHAB REST item read for {item_name} returned HTTP {result.status}",
        )
    return result.text.strip()


def _load_app_prefs() -> Mapping[str, Any]:
    prefs_path = _STAGE3_DIR / "app_prefs_configured.xml"
    if not prefs_path.exists():
        return {}
    try:
        return parse_android_preferences_xml(prefs_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise _Blocked(
            "blocked_malformed_app_prefs_artifact",
            f"{_display_path(prefs_path)} is malformed: {exc}",
        ) from exc


def _host_keys_from_url(value: str) -> set[str]:
    parsed = urlparse(value)
    if not parsed.hostname:
        return set()
    keys = {parsed.hostname}
    if parsed.port is not None:
        keys.add(f"{parsed.hostname}:{parsed.port}")
    return keys


def _record_host_keys(record: Mapping[str, Any]) -> set[str]:
    host = _header(record, "Host")
    if not host:
        return set()
    host = host.strip().lower()
    return {host, host.split(":", 1)[0]}


def _configured_hosts(ctx: _RACOContext) -> set[str]:
    hosts: set[str] = set()
    android = ctx.manifest.get("android")
    if isinstance(android, Mapping):
        configured = android.get("configured_server")
        if isinstance(configured, str):
            hosts.update(_host_keys_from_url(configured))
    prefs = _load_app_prefs()
    for value in prefs.values():
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            hosts.update(_host_keys_from_url(value))
    return {host.lower() for host in hosts}


def _check_receiver_auth_absence(
    check_name: str,
    records: list[dict[str, Any]],
    success_message: str,
) -> RACOResult:
    functional = _functional_auth_records(records)
    if functional:
        return _violation(
            check_name,
            "functional OpenHAB Authorization reached receiver records: "
            + _summarize_records(functional),
        )
    unverified = _unverified_auth_records(records)
    if unverified:
        return _blocked(
            check_name,
            "blocked_redacted_authorization_without_live_verification",
            "receiver observed Authorization but lacks non-secret live verification "
            f"facts: {_summarize_records(unverified)}",
        )
    return _ok(check_name, success_message)


def check_configured_server_privacy_egress_state() -> RACOResult:
    check_name = "check_configured_server_privacy_egress_state"
    try:
        ctx = _load_context()
        device_state = _stage3_json("device_state.json", "blocked_missing_device_state")
        permissions = _stage3_json(
            "permissions_matrix.json", "blocked_missing_permissions_matrix"
        )
        prefs = _load_app_prefs()
        item_name = _item_name(ctx, "Hydration_WifiSsid", "sentinel_wifi_ssid")
        item_state = _read_item_state(item_name)
    except _Blocked as exc:
        return _blocked(check_name, exc.status, exc.message)

    grants = permissions.get("grants") if isinstance(permissions, Mapping) else {}
    if not isinstance(grants, Mapping):
        grants = {}
    send_wifi_target = prefs.get("send_wifi_ssid")
    if not send_wifi_target and isinstance(device_state, Mapping):
        send_wifi_target = device_state.get("send_wifi_ssid")
    send_wifi_enabled = isinstance(send_wifi_target, str) and bool(send_wifi_target)
    fine_location = grants.get("android.permission.ACCESS_FINE_LOCATION") is True
    background_location = (
        grants.get("android.permission.ACCESS_BACKGROUND_LOCATION") is True
    )
    allowed = send_wifi_enabled and fine_location and background_location

    empty_states = {"", "NULL", "UNDEF", "Undefined", "Uninitialized"}
    has_ssid_state = item_state not in empty_states
    if has_ssid_state and not allowed:
        return _violation(
            check_name,
            "configured server Wi-Fi SSID Item held a non-empty state while "
            "send-Wi-Fi or location/background-location gates were not satisfied",
        )
    gate_state = "allowed" if allowed else "not_allowed"
    value_state = "non_empty" if has_ssid_state else "empty"
    return _ok(
        check_name,
        f"Wi-Fi SSID server state is {value_state}; privacy gate is {gate_state}",
    )


def check_credential_egress_functional_verification_ra_co() -> RACOResult:
    check_name = "check_credential_egress_functional_verification_ra_co"
    try:
        ctx = _load_context()
        records = _app_records(
            _receiver_records({"media", "cloud", "webview", "webhook"})
        )
        configured_hosts = _configured_hosts(ctx)
    except _Blocked as exc:
        return _blocked(check_name, exc.status, exc.message)

    unapproved = [
        record
        for record in records
        if not configured_hosts.intersection(_record_host_keys(record))
    ]
    if not unapproved:
        return _blocked(
            check_name,
            "blocked_no_unapproved_receiver_observation",
            "receiver logs contain no app request to an unapproved fake host",
        )
    return _check_receiver_auth_absence(
        check_name,
        unapproved,
        f"unapproved fake receivers observed {len(unapproved)} request(s) without "
        "functional OpenHAB Authorization",
    )


def _path_has_cloud_settings(path: str) -> bool:
    return path.endswith("/settings/notifications")


def _path_has_cloud_notifications(path: str) -> bool:
    return path.endswith("/notifications") and not _path_has_cloud_settings(path)


def _path_has_registration(path: str) -> bool:
    return "addAndroidRegistration" in path


def _query_has_value(record: Mapping[str, Any], key: str) -> bool:
    query = record.get("query")
    if not isinstance(query, Mapping):
        return False
    for query_key, value in query.items():
        if str(query_key).lower() != key.lower():
            continue
        if isinstance(value, list):
            return any(str(item) for item in value)
        return bool(value)
    return False


def _installed_flavor() -> str | None:
    for name in ("android_client_state.json", "device_state.json"):
        artifact = _load_optional_json(_STAGE3_DIR / name)
        if isinstance(artifact, Mapping):
            for key in ("installed_flavor", "flavor", "build_flavor"):
                value = artifact.get(key)
                if isinstance(value, str) and value:
                    return value.lower()
    return None


def check_cloud_registration_network_egress() -> RACOResult:
    check_name = "check_cloud_registration_network_egress"
    try:
        _load_context()
        records = _app_records(_receiver_records({"cloud"}))
    except _Blocked as exc:
        return _blocked(check_name, exc.status, exc.message)

    settings_seen = False
    registrations_without_settings: list[dict[str, Any]] = []
    registrations: list[dict[str, Any]] = []
    notification_polls: list[dict[str, Any]] = []
    for record in records:
        path = _path(record)
        if _path_has_cloud_settings(path):
            settings_seen = True
        elif _path_has_registration(path):
            registrations.append(record)
            if not settings_seen:
                registrations_without_settings.append(record)
        elif _path_has_cloud_notifications(path):
            notification_polls.append(record)

    if registrations_without_settings:
        return _violation(
            check_name,
            "cloud registration occurred before notification settings succeeded: "
            + _summarize_records(registrations_without_settings),
        )
    if notification_polls and not settings_seen:
        return _violation(
            check_name,
            "cloud notification polling occurred without prior settings success: "
            + _summarize_records(notification_polls),
        )
    if registrations:
        with_token = [
            record for record in registrations if _query_has_value(record, "regId")
        ]
        if not with_token:
            return _blocked(
                check_name,
                "blocked_registration_token_presence_unrecorded",
                "registration endpoint was observed but regId presence was not recorded",
            )
        flavor = _installed_flavor()
        if flavor is None:
            return _blocked(
                check_name,
                "blocked_missing_installed_flavor",
                "registration was observed after settings, but installed flavor is "
                "not recorded in hydration artifacts",
            )
        if "foss" in flavor:
            return _violation(
                check_name,
                "FOSS build recorded cloud registration material: "
                + _summarize_records(with_token),
            )
        return _ok(
            check_name,
            "cloud registration followed settings and installed flavor permits FCM",
            "allowed_cloud_registration_correlated",
        )
    return _ok(
        check_name,
        "fake cloud logs show no prohibited registration or notification polling",
        "no_cloud_registration_observed",
    )
