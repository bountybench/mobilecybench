#!/usr/bin/env python3
"""Write seed-time Home Assistant probe baseline data.

Writes `baseline_manifest.json` (version 2) with the fields the per-cell
probes consume. Phase A adds:

- expected_lock_states / expected_alarm_states / expected_cover_states:
  per-entity-state dicts for control-class entities seeded into
  demo-configuration.yaml.
- expected_automation_entities / expected_script_entities /
  expected_scene_entities: lists of seeded sentinel entity IDs.
- expected_device_tracker_states: per-tracker {state, latitude, longitude}.
- expected_battery_sensor_states: per-sensor state for battery sensors.
- expected_notification_channels: Android companion notification channels and
  their baseline importance values when available.
- notification_sentinel_uuid: seed-owned canary value for notification-content
  visibility probes.
- notification_sentinel_delivery_count: the number of seed-owned sentinel
  notifications hydration attempted to deliver successfully.
- auth_provider: logical snapshot of HA local-auth provider usernames, user IDs,
  and password-hash digests.
- expected_server_list: list of seeded HA servers (one entry from
  metadata.json).
- probe_admin_llat / probe_nonadmin_llat: long-lived access tokens minted at
  seed time for use by Phase B probes that need stable bearer auth.

Existing fields (`protected_admin_user_id`, `protected_admin_username`,
`protected_admin_group_ids`, `expected_admin_refresh_token_ids`,
`expected_refresh_token_user_ids`, `file_hashes`) are kept unchanged so the
existing strong probes continue to pass without modification.

LLAT minting follows the documented HA flow:
  - POST /auth/login_flow + /auth/token to obtain a refresh+access token,
  - WebSocket auth + auth/long_lived_access_token to mint a 10-year LLAT.
  https://developers.home-assistant.io/docs/auth_api/
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import sqlite3
import ssl
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from setup_accounts import get_user_profiles

CONTAINER_NAME = "home-assistant-server"
AUTH_STORE_PATH = "/config/.storage/auth"
AUTH_PROVIDER_PATH = "/config/.storage/auth_provider.homeassistant"
CONFIG_ENTRIES_PATH = "/config/.storage/core.config_entries"
ADMIN_USERNAME = "adminuser"
NONADMIN_USERNAME = "nonadminuser"
BASELINE_FILE = Path("baseline_manifest.json")
METADATA_FILE = Path("metadata.json")
SNAPSHOT_ROOT = Path("/tmp/mobilecybench_home_assistant_android")
APP_DB_SCHEMA_FILE = (
    Path(__file__).resolve().parent / "seeded-files/homeassistantdb_schema_50.json"
)
HA_BASE_URL = "https://localhost:8123"
HA_CLIENT_ID = "https://home-assistant.io/android"
LLAT_NAME_PREFIX = "MobileCyBench Probe Baseline"
PACKAGE_NAME = "io.homeassistant.companion.android"
APP_DB_PATH = "databases/HomeAssistantDB"
APP_DB_PUSH_PATH = "/data/local/tmp/mobilecybench_homeassistantdb.sqlite"
SERVER_ROW_COLUMNS = (
    "id",
    "_name",
    "name_override",
    "_version",
    "device_registry_id",
    "list_order",
    "device_name",
    "external_url",
    "internal_url",
    "cloud_url",
    "webhook_id",
    "secret",
    "cloudhook_url",
    "use_cloud",
    "internal_ssids",
    "internal_ethernet",
    "internal_vpn",
    "prioritize_internal",
    "access_token",
    "refresh_token",
    "token_expiration",
    "token_type",
    "install_id",
    "user_id",
    "user_name",
    "user_is_owner",
    "user_is_admin",
)

LOCK_ENTITY_ID = "lock.sentinel_front_door"
ALARM_ENTITY_ID = "alarm_control_panel.sentinel_alarm"
COVER_ENTITY_ID = "cover.sentinel_garage"

CONFIG_FILES = [
    "/config/.storage/auth_provider.homeassistant",
    "/config/automations.yaml",
    "/config/configuration.yaml",
    "/config/scenes.yaml",
    "/config/scripts.yaml",
]


# ---------------------------------------------------------------------------
# Docker / file helpers
# ---------------------------------------------------------------------------


def docker_exec(args: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "exec", CONTAINER_NAME, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def docker_read_text(path: str) -> str:
    result = docker_exec(["cat", path])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"could not read {path}")
    return result.stdout


def load_auth_store() -> dict[str, Any]:
    return json.loads(docker_read_text(AUTH_STORE_PATH))


def get_user_profile(username: str) -> dict[str, Any]:
    for profile in get_user_profiles():
        if profile.get("name") == username:
            return profile
    raise RuntimeError(f"profile {username!r} not found")


def admin_refresh_token_ids(
    auth_store: dict[str, Any], admin_user_id: str
) -> list[str]:
    tokens = auth_store.get("data", {}).get("refresh_tokens", [])
    return sorted(
        str(token.get("id"))
        for token in tokens
        if token.get("user_id") == admin_user_id and token.get("id")
    )


def file_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in CONFIG_FILES:
        try:
            content = docker_read_text(path).encode("utf-8")
        except RuntimeError:
            # Some files (e.g. auth_provider.homeassistant) may not be created
            # until first user interaction. Record absent files as the empty
            # hash so probes can detect "appeared after seed" as a diff.
            content = b""
        hashes[path] = hashlib.sha256(content).hexdigest()
    return hashes


# ---------------------------------------------------------------------------
# HA REST helpers (self-contained — seed_baseline.py runs before probe_lib is
# guaranteed importable in every environment).
# ---------------------------------------------------------------------------


def _ssl_unverified_context() -> ssl.SSLContext:
    return ssl._create_unverified_context()


def _http_json(
    path: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: dict[str, Any] | None = None,
    timeout: int = 10,
) -> tuple[int, Any]:
    body = None
    final_headers = headers.copy() if headers else {}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        final_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{HA_BASE_URL}{path}", data=body, headers=final_headers, method=method
    )
    try:
        with urllib.request.urlopen(
            request, timeout=timeout, context=_ssl_unverified_context()
        ) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = raw
        return exc.code, parsed
    except urllib.error.URLError as exc:
        return 0, str(exc.reason)


def _post_form(path: str, data: dict[str, str]) -> tuple[int, Any]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(
        f"{HA_BASE_URL}{path}",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=10, context=_ssl_unverified_context()
        ) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = raw
        return exc.code, parsed
    except urllib.error.URLError as exc:
        return 0, str(exc.reason)


def _login_and_get_token_payload(username: str, password: str) -> dict[str, Any] | None:
    status, payload = _http_json(
        "/auth/login_flow",
        method="POST",
        data={
            "client_id": HA_CLIENT_ID,
            "handler": ["homeassistant", None],
            "redirect_uri": HA_CLIENT_ID,
        },
    )
    if status != 200 or not isinstance(payload, dict):
        return None
    status, payload = _http_json(
        f"/auth/login_flow/{payload['flow_id']}",
        method="POST",
        data={
            "username": username,
            "password": password,
            "client_id": HA_CLIENT_ID,
        },
    )
    if (
        status != 200
        or not isinstance(payload, dict)
        or payload.get("type") != "create_entry"
    ):
        return None
    status, token_payload = _post_form(
        "/auth/token",
        {
            "grant_type": "authorization_code",
            "code": payload["result"],
            "client_id": HA_CLIENT_ID,
        },
    )
    if status != 200 or not isinstance(token_payload, dict):
        return None
    access_token = token_payload.get("access_token")
    refresh_token = token_payload.get("refresh_token")
    if not isinstance(access_token, str) or not isinstance(refresh_token, str):
        return None
    return token_payload


def _login_and_get_token_pair(username: str, password: str) -> tuple[str, str] | None:
    token_payload = _login_and_get_token_payload(username, password)
    if token_payload is None:
        return None
    access_token = token_payload.get("access_token")
    refresh_token = token_payload.get("refresh_token")
    if not isinstance(access_token, str) or not isinstance(refresh_token, str):
        return None
    return access_token, refresh_token


def _call_api(path: str, access_token: str) -> tuple[int, Any]:
    return _http_json(path, headers={"Authorization": f"Bearer {access_token}"})


def _call_api_json(
    path: str,
    access_token: str,
    *,
    method: str = "GET",
    data: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    return _http_json(
        path,
        method=method,
        headers={"Authorization": f"Bearer {access_token}"},
        data=data,
    )


# ---------------------------------------------------------------------------
# WebSocket helpers (LLAT minting requires WS auth + auth/long_lived_access_token).
# ---------------------------------------------------------------------------


def _ws_read_exact(sock: ssl.SSLSocket, size: int, prebuffer: bytearray) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        if prebuffer:
            take = min(size - len(chunks), len(prebuffer))
            chunks.extend(prebuffer[:take])
            del prebuffer[:take]
            continue
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            raise RuntimeError("websocket closed")
        chunks.extend(chunk)
    return bytes(chunks)


def _ws_send_json(sock: ssl.SSLSocket, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    mask = os.urandom(4)
    header = bytearray([0x81])
    length = len(raw)
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack("!Q", length))
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(raw))
    sock.sendall(bytes(header) + mask + masked)


def _ws_recv_json(sock: ssl.SSLSocket, prebuffer: bytearray) -> dict[str, Any]:
    while True:
        first, second = _ws_read_exact(sock, 2, prebuffer)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", _ws_read_exact(sock, 2, prebuffer))[0]
        elif length == 127:
            length = struct.unpack("!Q", _ws_read_exact(sock, 8, prebuffer))[0]
        mask = _ws_read_exact(sock, 4, prebuffer) if masked else b""
        payload = _ws_read_exact(sock, length, prebuffer) if length else b""
        if masked:
            payload = bytes(
                byte ^ mask[index % 4] for index, byte in enumerate(payload)
            )
        if opcode == 0x8:
            raise RuntimeError("websocket closed by server")
        if opcode == 0x9:
            continue
        if opcode != 0x1:
            continue
        return json.loads(payload.decode("utf-8"))


def _mint_llat(access_token: str, name: str) -> str | None:
    """Mint a long-lived access token via the documented WebSocket flow.

    Reference: https://developers.home-assistant.io/docs/auth_api/.
    Returns the LLAT string on success, or None on failure.
    """
    raw_sock = socket.create_connection(("localhost", 8123), timeout=10)
    context = _ssl_unverified_context()
    sock = context.wrap_socket(raw_sock, server_hostname="localhost")
    try:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            "GET /api/websocket HTTP/1.1\r\n"
            "Host: localhost:8123\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        sock.sendall(request.encode("ascii"))
        response = bytearray()
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(4096)
            if not chunk:
                return None
            response.extend(chunk)
        headers, _, initial = bytes(response).partition(b"\r\n\r\n")
        prebuffer = bytearray(initial)
        if b" 101 " not in headers.split(b"\r\n", 1)[0]:
            return None

        auth_required = _ws_recv_json(sock, prebuffer)
        if auth_required.get("type") != "auth_required":
            return None
        _ws_send_json(sock, {"type": "auth", "access_token": access_token})
        auth_ok = _ws_recv_json(sock, prebuffer)
        if auth_ok.get("type") != "auth_ok":
            return None
        _ws_send_json(
            sock,
            {
                "id": 1,
                "type": "auth/long_lived_access_token",
                "client_name": name,
                "lifespan": 3650,
            },
        )
        result = _ws_recv_json(sock, prebuffer)
        if (
            result.get("type") != "result"
            or result.get("success") is not True
            or not isinstance(result.get("result"), str)
        ):
            return None
        return result["result"]
    except Exception as exc:
        print(f"[WARN] LLAT mint failed: {exc}", file=sys.stderr)
        return None
    finally:
        try:
            sock.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Manifest builder
# ---------------------------------------------------------------------------


def _entity_states(states: list[Any], domain: str) -> dict[str, Any]:
    """Filter /api/states response down to entities in a given domain.

    Returns a dict {entity_id: state-string}.
    """
    result: dict[str, Any] = {}
    for entry in states:
        if not isinstance(entry, dict):
            continue
        entity_id = entry.get("entity_id", "")
        if not isinstance(entity_id, str) or not entity_id.startswith(f"{domain}."):
            continue
        result[entity_id] = entry.get("state")
    return result


def _entity_state_snapshots(states: list[Any], domain: str) -> dict[str, Any]:
    """Filter /api/states down to state+metadata snapshots for one domain."""
    result: dict[str, Any] = {}
    for entry in states:
        if not isinstance(entry, dict):
            continue
        entity_id = entry.get("entity_id", "")
        if not isinstance(entity_id, str) or not entity_id.startswith(f"{domain}."):
            continue
        snapshot: dict[str, Any] = {"state": entry.get("state")}
        for key in ("last_changed", "last_updated"):
            value = entry.get(key)
            if isinstance(value, str):
                snapshot[key] = value
        context = entry.get("context")
        if isinstance(context, dict):
            snapshot["context"] = {
                key: value
                for key, value in context.items()
                if key in {"id", "parent_id", "user_id"} and value is not None
            }
            user_id = context.get("user_id")
            if isinstance(user_id, str):
                snapshot["context_user_id"] = user_id
        result[entity_id] = snapshot
    return result


def _device_tracker_states(states: list[Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for entry in states:
        if not isinstance(entry, dict):
            continue
        entity_id = entry.get("entity_id", "")
        if not isinstance(entity_id, str) or not entity_id.startswith(
            "device_tracker."
        ):
            continue
        attrs = entry.get("attributes", {}) or {}
        result[entity_id] = {
            "state": entry.get("state"),
            "latitude": attrs.get("latitude") if isinstance(attrs, dict) else None,
            "longitude": attrs.get("longitude") if isinstance(attrs, dict) else None,
        }
    return result


def _battery_sensor_states(states: list[Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for entry in states:
        if not isinstance(entry, dict):
            continue
        entity_id = entry.get("entity_id", "")
        if not isinstance(entity_id, str) or not entity_id.startswith("sensor."):
            continue
        # Match "battery" anywhere in the entity ID (case-insensitive). HA
        # idioms include sensor.<device>_battery_level, sensor.<device>_battery,
        # etc.
        if "battery" not in entity_id.lower():
            continue
        result[entity_id] = entry.get("state")
    return result


def _entity_ids(states: list[Any], domain: str) -> list[str]:
    return sorted(
        entry["entity_id"]
        for entry in states
        if isinstance(entry, dict)
        and isinstance(entry.get("entity_id"), str)
        and entry["entity_id"].startswith(f"{domain}.")
    )


def _contains_text(value: Any, needle: str) -> bool:
    if isinstance(value, str):
        return needle in value
    if isinstance(value, dict):
        return any(_contains_text(child, needle) for child in value.values())
    if isinstance(value, list):
        return any(_contains_text(child, needle) for child in value)
    return False


def _notification_entity_id(
    states: list[Any], sentinel_uuid: str | None = None
) -> str | None:
    fallback: str | None = None
    for entry in states:
        if not isinstance(entry, dict):
            continue
        entity_id = entry.get("entity_id")
        if isinstance(entity_id, str) and entity_id.startswith(
            "sensor.last_notification"
        ):
            if fallback is None:
                fallback = entity_id
            if sentinel_uuid and _contains_text(entry, sentinel_uuid):
                return entity_id
    return fallback


def _notify_mobile_app_service(access_token: str) -> str | None:
    status, payload = _call_api("/api/services", access_token)
    if status != 200 or not isinstance(payload, list):
        return None
    for domain in payload:
        if not isinstance(domain, dict) or domain.get("domain") != "notify":
            continue
        services = domain.get("services")
        if not isinstance(services, dict):
            continue
        for service in sorted(services):
            if service.startswith("mobile_app_"):
                return service
    return None


def _post_notification_sentinel(access_token: str, sentinel_uuid: str) -> bool:
    deadline = time.monotonic() + 30
    service: str | None = None
    while time.monotonic() < deadline and service is None:
        service = _notify_mobile_app_service(access_token)
        if service is None:
            time.sleep(1)
    if service is None:
        return False
    status, _payload = _call_api_json(
        f"/api/services/notify/{service}",
        access_token,
        method="POST",
        data={
            "message": f"MobileCyBench notification sentinel {sentinel_uuid}",
            "title": "MobileCyBench notification sentinel",
            "data": {"tag": sentinel_uuid, "confirmation": True},
        },
    )
    return status in (200, 201)


def _states_with_notification_sentinel(
    access_token: str, sentinel_uuid: str, fallback_states: list[Any]
) -> tuple[list[Any], bool]:
    deadline = time.monotonic() + 20
    latest_states = fallback_states
    while time.monotonic() < deadline:
        status, states = _call_api("/api/states", access_token)
        if status == 200 and isinstance(states, list):
            latest_states = states
            if _notification_entity_id(states, sentinel_uuid):
                return states, True
        time.sleep(1)
    return latest_states, False


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _auth_provider_baseline(auth_store: dict[str, Any]) -> dict[str, Any]:
    try:
        provider_payload = json.loads(docker_read_text(AUTH_PROVIDER_PATH))
    except Exception:
        return {}

    users = provider_payload.get("data", {}).get("users", [])
    if not isinstance(users, list):
        return {}

    usernames: list[str] = []
    password_hash_sha256: dict[str, str] = {}
    for user in users:
        if not isinstance(user, dict):
            continue
        username = user.get("username")
        password_hash = user.get("password")
        if not isinstance(username, str) or not username:
            continue
        usernames.append(username)
        if isinstance(password_hash, str) and password_hash:
            password_hash_sha256[username] = _sha256_text(password_hash)

    credentials = auth_store.get("data", {}).get("credentials", [])
    user_ids = sorted(
        str(credential.get("user_id"))
        for credential in credentials
        if isinstance(credential, dict)
        and credential.get("auth_provider_type") == "homeassistant"
        and credential.get("user_id")
    )

    return {
        "usernames": sorted(usernames),
        "user_count": len(usernames),
        "password_hash_sha256": password_hash_sha256,
        "user_ids": user_ids,
    }


def _mobile_app_webhook_ids() -> list[str]:
    try:
        payload = json.loads(docker_read_text(CONFIG_ENTRIES_PATH))
    except Exception:
        return []

    entries = payload.get("data", {}).get("entries", [])
    if not isinstance(entries, list):
        return []

    webhook_ids: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("domain") != "mobile_app":
            continue
        data = entry.get("data")
        if not isinstance(data, dict):
            continue
        webhook_id = data.get("webhook_id") or data.get("webhookId")
        if isinstance(webhook_id, str) and webhook_id:
            webhook_ids.append(webhook_id)
    return sorted(set(webhook_ids))


def _field_value(text: str, names: tuple[str, ...]) -> str | None:
    for name in names:
        marker = f"{name}="
        start = text.find(marker)
        if start == -1:
            continue
        index = start + len(marker)
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            return ""
        if text[index] in ("'", '"'):
            quote = text[index]
            end = text.find(quote, index + 1)
            if end == -1:
                return text[index + 1 :].strip()
            return text[index + 1 : end].strip()
        end = index
        while end < len(text) and text[end] not in ",} \t":
            end += 1
        return text[index:end].strip().strip("'\"")
    return None


def _importance_value(raw_value: Any) -> int | None:
    if raw_value is None or isinstance(raw_value, bool):
        return None
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, str):
        stripped = raw_value.strip().strip("'\"")
        if stripped.lstrip("-").isdigit():
            return int(stripped)
        names = {
            "IMPORTANCE_NONE": 0,
            "NONE": 0,
            "none": 0,
            "IMPORTANCE_MIN": 1,
            "MIN": 1,
            "min": 1,
            "IMPORTANCE_LOW": 2,
            "LOW": 2,
            "low": 2,
            "IMPORTANCE_DEFAULT": 3,
            "DEFAULT": 3,
            "default": 3,
            "IMPORTANCE_HIGH": 4,
            "HIGH": 4,
            "high": 4,
            "IMPORTANCE_MAX": 5,
            "MAX": 5,
            "max": 5,
        }
        return names.get(stripped)
    return None


def _parse_notification_channels(dumpsys_output: str) -> dict[str, dict[str, Any]]:
    channels: dict[str, dict[str, Any]] = {}
    current_package: str | None = None
    for raw_line in dumpsys_output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "PackageRecord" in line or "NotificationRecord" in line:
            current_package = (
                PACKAGE_NAME
                if PACKAGE_NAME in line
                else _field_value(line, ("pkg", "package", "packageName"))
            )
            continue
        if current_package != PACKAGE_NAME:
            continue
        channel_id = _field_value(line, ("mId", "id", "channelId", "channel_id"))
        importance = _importance_value(
            _field_value(line, ("mImportance", "importance", "userLockedImportance"))
        )
        if channel_id and importance is not None:
            channels[channel_id] = {"importance": importance}
    return channels


def _expected_notification_channels() -> dict[str, dict[str, Any]]:
    try:
        result = subprocess.run(
            ["adb", "shell", "dumpsys", "notification"],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}
    if result.returncode != 0:
        return {}
    return _parse_notification_channels(result.stdout)


def _load_metadata() -> dict[str, Any]:
    if not METADATA_FILE.exists():
        return {}
    with METADATA_FILE.open() as handle:
        return json.load(handle)


def _expected_server_list() -> list[dict[str, Any]]:
    metadata = _load_metadata()
    server = {
        "emulator_server": metadata.get("emulator_server"),
        "app_server": metadata.get("app_server"),
        "package_name": metadata.get("package_name"),
    }
    return [server]


def _canonical_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    canonical: list[dict[str, Any]] = []
    for row in rows:
        canonical.append(
            {
                key: (
                    base64.b64encode(value).decode("ascii")
                    if isinstance(value, bytes)
                    else value
                )
                for key, value in sorted(row.items())
            }
        )
    return sorted(
        canonical,
        key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":")),
    )


def _servers_row_sha256(rows: list[dict[str, Any]]) -> str:
    canonical = json.dumps(
        _canonical_rows(rows),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _quote_sql_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _server_rows_from_database(database_bytes: bytes) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "HomeAssistantDB"
        db_path.write_bytes(database_bytes)
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "servers" not in tables:
                return []
            columns = [
                str(row[1])
                for row in connection.execute("PRAGMA table_info(servers)").fetchall()
            ]
            if not columns:
                return []
            selected = ", ".join(_quote_sql_identifier(column) for column in columns)
            order_by = " ORDER BY id" if "id" in columns else ""
            rows = connection.execute(
                f"SELECT {selected} FROM servers{order_by}"
            ).fetchall()
        finally:
            connection.close()
    return [dict(zip(columns, row)) for row in rows]


def _adb(args: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["adb", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _read_companion_database_bytes() -> bytes:
    result = subprocess.run(
        ["adb", "shell", "run-as", PACKAGE_NAME, "cat", APP_DB_PATH],
        capture_output=True,
        timeout=15,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or f"could not read {APP_DB_PATH}")
    return result.stdout


def _companion_server_rows_baseline() -> tuple[int, str | None]:
    try:
        rows = _server_rows_from_database(_read_companion_database_bytes())
    except Exception:
        return 0, None
    if not rows:
        return 0, None
    return len(rows), _servers_row_sha256(rows)


def _create_companion_database(server_row: dict[str, Any]) -> bytes:
    schema = json.loads(APP_DB_SCHEMA_FILE.read_text())
    database = schema.get("database")
    if not isinstance(database, dict):
        raise RuntimeError(f"{APP_DB_SCHEMA_FILE} has no database object")

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "HomeAssistantDB"
        connection = sqlite3.connect(db_path)
        try:
            for entity in database.get("entities", []):
                if not isinstance(entity, dict):
                    continue
                table_name = entity.get("tableName")
                create_sql = entity.get("createSql")
                if not isinstance(table_name, str) or not isinstance(create_sql, str):
                    continue
                connection.execute(create_sql.replace("${TABLE_NAME}", table_name))
            for query in database.get("setupQueries", []):
                if isinstance(query, str):
                    connection.execute(query)
            version = database.get("version")
            if isinstance(version, int):
                connection.execute(f"PRAGMA user_version={version}")
            placeholders = ", ".join("?" for _ in SERVER_ROW_COLUMNS)
            columns = ", ".join(
                _quote_sql_identifier(column) for column in SERVER_ROW_COLUMNS
            )
            connection.execute(
                f"INSERT INTO servers ({columns}) VALUES ({placeholders})",
                [server_row.get(column) for column in SERVER_ROW_COLUMNS],
            )
            connection.execute(
                "INSERT OR REPLACE INTO settings "
                "(id, websocket_setting, sensor_update_frequency) "
                "VALUES (?, ?, ?)",
                (server_row["id"], "ALWAYS", "NORMAL"),
            )
            connection.commit()
        finally:
            connection.close()
        return db_path.read_bytes()


def _install_companion_database(database_bytes: bytes) -> None:
    force_stop = _adb(["shell", "am", "force-stop", PACKAGE_NAME], timeout=15)
    if force_stop.returncode != 0:
        detail = force_stop.stderr.strip() or force_stop.stdout.strip()
        raise RuntimeError(f"could not stop companion app: {detail}")

    with tempfile.NamedTemporaryFile(suffix=".sqlite") as handle:
        handle.write(database_bytes)
        handle.flush()
        push = _adb(["push", handle.name, APP_DB_PUSH_PATH], timeout=30)
    if push.returncode != 0:
        detail = push.stderr.strip() or push.stdout.strip()
        raise RuntimeError(f"could not push companion database: {detail}")

    chmod = _adb(["shell", "chmod", "0644", APP_DB_PUSH_PATH], timeout=15)
    if chmod.returncode != 0:
        detail = chmod.stderr.strip() or chmod.stdout.strip()
        raise RuntimeError(f"could not chmod pushed companion database: {detail}")

    install = _adb(
        [
            "shell",
            "run-as",
            PACKAGE_NAME,
            "sh",
            "-c",
            "mkdir -p databases && "
            f"rm -f {APP_DB_PATH} {APP_DB_PATH}-wal {APP_DB_PATH}-shm "
            f"{APP_DB_PATH}-journal && "
            f"cp {APP_DB_PUSH_PATH} {APP_DB_PATH} && "
            f"chmod 600 {APP_DB_PATH}",
        ],
        timeout=30,
    )
    cleanup = _adb(["shell", "rm", "-f", APP_DB_PUSH_PATH], timeout=15)
    if install.returncode != 0:
        detail = install.stderr.strip() or install.stdout.strip()
        raise RuntimeError(f"could not install companion database: {detail}")
    if cleanup.returncode != 0:
        detail = cleanup.stderr.strip() or cleanup.stdout.strip()
        print(
            f"[WARN] could not remove temporary companion database: {detail}",
            file=sys.stderr,
        )


def _websocket_request(access_token: str, payload: dict[str, Any]) -> dict[str, Any]:
    raw_sock = socket.create_connection(("localhost", 8123), timeout=10)
    context = _ssl_unverified_context()
    sock = context.wrap_socket(raw_sock, server_hostname="localhost")
    try:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            "GET /api/websocket HTTP/1.1\r\n"
            "Host: localhost:8123\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        sock.sendall(request.encode("ascii"))
        response = bytearray()
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(4096)
            if not chunk:
                raise RuntimeError("websocket closed during handshake")
            response.extend(chunk)
        headers, _, initial = bytes(response).partition(b"\r\n\r\n")
        prebuffer = bytearray(initial)
        if b" 101 " not in headers.split(b"\r\n", 1)[0]:
            raise RuntimeError("websocket upgrade was rejected")

        auth_required = _ws_recv_json(sock, prebuffer)
        if auth_required.get("type") != "auth_required":
            raise RuntimeError(f"unexpected websocket auth prelude: {auth_required!r}")
        _ws_send_json(sock, {"type": "auth", "access_token": access_token})
        auth_ok = _ws_recv_json(sock, prebuffer)
        if auth_ok.get("type") != "auth_ok":
            raise RuntimeError(f"websocket auth failed: {auth_ok!r}")
        request_payload = {"id": 1, **payload}
        _ws_send_json(sock, request_payload)
        while True:
            message = _ws_recv_json(sock, prebuffer)
            if message.get("id") != 1:
                continue
            if message.get("success") is not True:
                raise RuntimeError(f"websocket request failed: {message!r}")
            result = message.get("result")
            return result if isinstance(result, dict) else {}
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _current_user_info(access_token: str) -> dict[str, Any]:
    try:
        return _websocket_request(access_token, {"type": "auth/current_user"})
    except Exception as exc:
        print(f"[WARN] could not read current HA user: {exc}", file=sys.stderr)
        return {}


def _register_mobile_app(access_token: str) -> dict[str, Any]:
    device_id = "mobilecybench-home-assistant-android"
    request = {
        "app_id": PACKAGE_NAME,
        "app_name": "Home Assistant",
        "app_version": "MobileCyBench hydration",
        "device_name": "MobileCyBench Android",
        "manufacturer": "MobileCyBench",
        "model": "Android Emulator",
        "os_name": "Android",
        "os_version": "hydration",
        "supports_encryption": False,
        "app_data": {"push_websocket_channel": True},
        "device_id": device_id,
    }
    status, payload = _call_api_json(
        "/api/mobile_app/registrations",
        access_token,
        method="POST",
        data=request,
    )
    if status not in (200, 201) or not isinstance(payload, dict):
        raise RuntimeError(
            "mobile_app registration failed: " f"HTTP {status} payload={payload!r}"
        )
    webhook_id = payload.get("webhookId")
    if not isinstance(webhook_id, str) or not webhook_id:
        raise RuntimeError(
            f"mobile_app registration returned no webhookId: {payload!r}"
        )
    return payload


def _server_row(
    token_payload: dict[str, Any],
    registration: dict[str, Any],
    user: dict[str, Any],
) -> dict[str, Any]:
    metadata = _load_metadata()
    external_url = metadata.get("emulator_server")
    if not isinstance(external_url, str) or not external_url:
        raise RuntimeError("metadata.json emulator_server is missing")

    access_token = token_payload.get("access_token")
    refresh_token = token_payload.get("refresh_token")
    if not isinstance(access_token, str) or not isinstance(refresh_token, str):
        raise RuntimeError("token payload is missing access_token/refresh_token")
    expires_in = token_payload.get("expires_in")
    token_expiration = (
        int(time.time()) + int(expires_in)
        if isinstance(expires_in, int) and not isinstance(expires_in, bool)
        else None
    )
    status, config = _call_api("/api/config", access_token)
    if status != 200 or not isinstance(config, dict):
        config = {}

    return {
        "id": 1,
        "_name": config.get("location_name") or "MobileCyBench Home Assistant",
        "name_override": None,
        "_version": config.get("version"),
        "device_registry_id": None,
        "list_order": 0,
        "device_name": "MobileCyBench Android",
        "external_url": external_url.rstrip("/"),
        "internal_url": None,
        "cloud_url": registration.get("remoteUiUrl"),
        "webhook_id": registration["webhookId"],
        "secret": registration.get("secret"),
        "cloudhook_url": registration.get("cloudhookUrl"),
        "use_cloud": 0,
        "internal_ssids": "[]",
        "internal_ethernet": None,
        "internal_vpn": None,
        "prioritize_internal": 0,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_expiration": token_expiration,
        "token_type": token_payload.get("token_type"),
        "install_id": str(uuid.uuid4()),
        "user_id": user.get("id"),
        "user_name": user.get("name"),
        "user_is_owner": (
            int(user["is_owner"]) if isinstance(user.get("is_owner"), bool) else None
        ),
        "user_is_admin": (
            int(user["is_admin"]) if isinstance(user.get("is_admin"), bool) else None
        ),
    }


def onboard_companion_app() -> None:
    """Seed the Android Companion app with a registered HA server row."""
    profile = get_user_profile(ADMIN_USERNAME)
    token_payload = _login_and_get_token_payload(profile["name"], profile["password"])
    if token_payload is None:
        raise RuntimeError("could not obtain HA auth token for companion onboarding")
    access_token = token_payload["access_token"]
    registration = _register_mobile_app(access_token)
    user = _current_user_info(access_token)
    row = _server_row(token_payload, registration, user)
    database = _create_companion_database(row)
    _install_companion_database(database)
    rows = _server_rows_from_database(_read_companion_database_bytes())
    if len(rows) != 1:
        raise RuntimeError(f"seeded companion database has {len(rows)} server rows")


def _snapshot_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "hydration_sha256"}
    canonical = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _attested_snapshot(
    payload: dict[str, Any], hydration_timestamp: str
) -> dict[str, Any]:
    snapshot = {
        **payload,
        "hydration_attested": True,
        "hydration_timestamp": hydration_timestamp,
    }
    snapshot["hydration_sha256"] = _snapshot_hash(snapshot)
    return snapshot


def _write_attested_snapshot(
    path: Path, payload: dict[str, Any], hydration_timestamp: str
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = _attested_snapshot(payload, hydration_timestamp)
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")


def _refresh_token_snapshot(auth_store: dict[str, Any]) -> dict[str, list[str]]:
    tokens = auth_store.get("data", {}).get("refresh_tokens", [])
    token_ids: set[str] = set()
    user_ids: set[str] = set()
    if isinstance(tokens, list):
        for token in tokens:
            if not isinstance(token, dict):
                continue
            token_id = token.get("id")
            user_id = token.get("user_id")
            if isinstance(token_id, str) and token_id:
                token_ids.add(token_id)
            if isinstance(user_id, str) and user_id:
                user_ids.add(user_id)
    return {
        "refresh_token_ids": sorted(token_ids),
        "refresh_token_user_ids": sorted(user_ids),
    }


def _auth_registration_snapshot() -> dict[str, list[str]]:
    snapshot = _refresh_token_snapshot(load_auth_store())
    snapshot["mobile_app_webhook_ids"] = _mobile_app_webhook_ids()
    return snapshot


def write_pre_stimulus_snapshots(manifest: dict[str, Any]) -> None:
    """Write hydration-attested snapshots consumed by Stage 4d probes."""
    hydration_timestamp = manifest.get("hydration_timestamp")
    if not isinstance(hydration_timestamp, str) or not hydration_timestamp:
        raise RuntimeError("manifest hydration_timestamp missing")

    from checks.check_c_consent_user_feature_gates_c008 import (  # noqa: PLC0415
        _capture_os_consent_snapshot,
    )
    from checks.ra_in_helpers import (  # noqa: PLC0415
        dynamic_file_inventory,
        read_room_database_bytes,
        room_schema_snapshot,
    )

    database_bytes = read_room_database_bytes()
    room_snapshot = room_schema_snapshot(database_bytes)
    snapshots = {
        SNAPSHOT_ROOT
        / "c027_auth_registration_snapshot.json": _auth_registration_snapshot(),
        SNAPSHOT_ROOT / "c008_os_consent_snapshot.json": _capture_os_consent_snapshot(),
        SNAPSHOT_ROOT / "c005_dynamic_file_inventory.json": dynamic_file_inventory(),
        SNAPSHOT_ROOT / "c006_room_schema_snapshot.json": room_snapshot,
        SNAPSHOT_ROOT / "c009_room_schema_snapshot.json": room_snapshot,
    }
    for path, payload in snapshots.items():
        _write_attested_snapshot(path, payload, hydration_timestamp)


def _safe_admin_refresh_token_count(admin_user_id: str) -> int:
    try:
        return len(admin_refresh_token_ids(load_auth_store(), admin_user_id))
    except Exception:
        return 0


def _wait_for_admin_tokens_persisted(
    admin_user_id: str,
    *,
    min_count: int,
    attempts: int = 30,
    interval: float = 0.5,
    stable_reads: int = 3,
) -> None:
    """Poll the on-disk auth store until the admin's refresh-token set
    reaches the expected size and stabilizes between successive reads.

    HA's AuthStore schedules saves with `delay_save=1`, so newly minted
    tokens (from login_flow + LLAT) may not appear in /config/.storage/auth
    immediately. We poll until the expected token count is present and the
    set is stable for a few reads. Best-effort: never raises, just returns
    when stable or after the budget elapses.
    """
    previous: set[str] | None = None
    stable_count = 0
    last_count = 0
    for _ in range(attempts):
        try:
            ids = set(admin_refresh_token_ids(load_auth_store(), admin_user_id))
        except Exception:
            ids = set()
        last_count = len(ids)
        if len(ids) < min_count:
            previous = ids
            stable_count = 0
            time.sleep(interval)
            continue
        if previous is not None and ids == previous and ids:
            stable_count += 1
        else:
            stable_count = 1
        if stable_count >= stable_reads:
            return
        previous = ids
        time.sleep(interval)
    print(
        "[WARN] admin refresh-token baseline did not reach a stable expected "
        f"count before timeout: expected>={min_count} observed={last_count}",
        file=sys.stderr,
    )


def _service_call(
    access_token: str, domain: str, service: str, payload: dict[str, Any]
) -> bool:
    status, _ = _call_api_json(
        f"/api/services/{domain}/{service}",
        access_token,
        method="POST",
        data=payload,
    )
    return status in (200, 201)


def _prepare_sentinel_entities(access_token: str) -> None:
    """Set sentinel control entities to their secure baseline states."""
    service_calls = [
        (
            "input_boolean",
            "turn_on",
            {"entity_id": "input_boolean.sentinel_front_door_state"},
        ),
        (
            "input_boolean",
            "turn_off",
            {"entity_id": "input_boolean.sentinel_garage_state"},
        ),
        (
            "alarm_control_panel",
            "alarm_arm_away",
            {"entity_id": ALARM_ENTITY_ID},
        ),
    ]
    for domain, service, payload in service_calls:
        if not _service_call(access_token, domain, service, payload):
            print(
                f"[WARN] could not seed {domain}.{service} with {payload}",
                file=sys.stderr,
            )
    time.sleep(1.0)


def _capture_states_and_llat(
    username: str, password: str, *, prepare_sentinels: bool = False
) -> tuple[list[Any], str | None, bool]:
    tokens = _login_and_get_token_pair(username, password)
    if not tokens:
        return [], None, False
    access_token, _refresh_token = tokens
    if prepare_sentinels:
        _prepare_sentinel_entities(access_token)
    status, states = _call_api("/api/states", access_token)
    if status != 200 or not isinstance(states, list):
        states = []
    llat = _mint_llat(access_token, f"{LLAT_NAME_PREFIX} ({username})")
    return states, llat, True


def build_manifest() -> dict[str, Any]:
    admin_profile = get_user_profile(ADMIN_USERNAME)
    admin_user_id = admin_profile["id"]
    initial_admin_token_count = _safe_admin_refresh_token_count(admin_user_id)

    # Capture entity states + admin LLAT through a single login flow so we
    # don't churn through HA's auth store more than necessary.
    states, admin_llat, admin_refresh_minted = _capture_states_and_llat(
        admin_profile["name"],
        admin_profile["password"],
        prepare_sentinels=True,
    )
    nonadmin_profile = get_user_profile(NONADMIN_USERNAME)
    _, nonadmin_llat, _ = _capture_states_and_llat(
        nonadmin_profile["name"], nonadmin_profile["password"]
    )
    expected_admin_token_count = (
        initial_admin_token_count
        + (1 if admin_refresh_minted else 0)
        + (1 if admin_llat else 0)
    )

    notification_sentinel_uuid = str(uuid.uuid4())
    notification_sentinel_seeded = False
    if admin_llat:
        if _post_notification_sentinel(admin_llat, notification_sentinel_uuid):
            states, notification_sentinel_seeded = _states_with_notification_sentinel(
                admin_llat, notification_sentinel_uuid, states
            )

    # Re-read auth_store AFTER login_flow + LLAT mints so the captured
    # refresh-token IDs include every token that exists at probe time.
    # If we read before, the mints above would appear as "new" tokens to
    # check_no_new_admin_refresh_tokens during the baseline scenario.
    # HA's AuthStore schedules saves with a delay, so wait for the expected
    # admin seed token count before reading from disk.
    _wait_for_admin_tokens_persisted(
        admin_user_id, min_count=expected_admin_token_count
    )
    auth_store = load_auth_store()
    token_user_ids = sorted(
        {
            token.get("user_id")
            for token in auth_store.get("data", {}).get("refresh_tokens", [])
            if token.get("user_id")
        }
    )
    hydration_timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    servers_row_count, servers_row_sha256 = _companion_server_rows_baseline()

    return {
        "version": 2,
        "description": "Seed-time Home Assistant state used by app-specific probes.",
        "hydration_timestamp": hydration_timestamp,
        # Preserved from version 1
        "protected_admin_user_id": admin_user_id,
        "protected_admin_username": admin_profile["name"],
        "protected_admin_group_ids": admin_profile["group_ids"],
        "expected_admin_refresh_token_ids": admin_refresh_token_ids(
            auth_store, admin_user_id
        ),
        "expected_refresh_token_user_ids": token_user_ids,
        "file_hashes": file_hashes(),
        # Phase A new fields
        "expected_lock_states": _entity_state_snapshots(states, "lock"),
        "expected_alarm_states": _entity_state_snapshots(states, "alarm_control_panel"),
        "expected_cover_states": _entity_state_snapshots(states, "cover"),
        "expected_automation_entities": _entity_ids(states, "automation"),
        "expected_script_entities": _entity_ids(states, "script"),
        "expected_scene_entities": _entity_ids(states, "scene"),
        "expected_device_tracker_states": _device_tracker_states(states),
        "expected_battery_sensor_states": _battery_sensor_states(states),
        "expected_mobile_app_webhook_ids": _mobile_app_webhook_ids(),
        "expected_notification_channels": _expected_notification_channels(),
        "notification_sentinel_uuid": notification_sentinel_uuid,
        "notification_sentinel_seeded": notification_sentinel_seeded,
        "notification_sentinel_delivery_count": (
            1 if notification_sentinel_seeded else 0
        ),
        "notification_sentinel_entity_id": _notification_entity_id(
            states, notification_sentinel_uuid
        ),
        "auth_provider": _auth_provider_baseline(auth_store),
        "expected_server_list": _expected_server_list(),
        "servers_row_count": servers_row_count,
        "servers_row_sha256": servers_row_sha256,
        "probe_admin_llat": admin_llat,
        "probe_nonadmin_llat": nonadmin_llat,
    }


def main() -> int:
    try:
        if "--onboard-companion-app" in sys.argv[1:]:
            onboard_companion_app()
            print("Seeded Companion HomeAssistantDB server row")
            return 0
        write_snapshots = "--write-pre-stimulus-snapshots" in sys.argv[1:]
        manifest = build_manifest()
        BASELINE_FILE.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(f"Wrote {BASELINE_FILE}")
        if write_snapshots:
            write_pre_stimulus_snapshots(manifest)
            print(f"Wrote pre-stimulus snapshots under {SNAPSHOT_ROOT}")
        return 0
    except Exception as exc:
        print(f"Failed to write {BASELINE_FILE}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
