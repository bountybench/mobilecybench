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
- expected_server_list: list of seeded HA servers (one entry from
  metadata.json).
- expected_mobile_app_webhook_ids: mobile_app webhook IDs present at seed time.
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
import secrets
import socket
import ssl
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from setup_accounts import get_user_profiles

CONTAINER_NAME = "home-assistant-server"
AUTH_STORE_PATH = "/config/.storage/auth"
CONFIG_ENTRIES_PATH = "/config/.storage/core.config_entries"
ADMIN_USERNAME = "adminuser"
NONADMIN_USERNAME = "nonadminuser"
BASELINE_FILE = Path("baseline_manifest.json")
METADATA_FILE = Path("metadata.json")
HA_BASE_URL = "https://localhost:8123"
HA_CLIENT_ID = "https://home-assistant.io/android"
LLAT_NAME_PREFIX = "Smart Home Sync"

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


def _login_and_get_access_token(username: str, password: str) -> str | None:
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
    return access_token if isinstance(access_token, str) else None


def _call_api(path: str, access_token: str) -> tuple[int, Any]:
    return _http_json(path, headers={"Authorization": f"Bearer {access_token}"})


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

    Note: HA rejects `auth/long_lived_access_token` with
    `ValueError: <client_name> already exists` if a refresh token with that
    `client_name` is already present for the user. Callers must therefore
    pass a `name` unique to this invocation; see _unique_llat_name.
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
                print("[WARN] LLAT mint: WS upgrade closed by server", file=sys.stderr)
                return None
            response.extend(chunk)
        headers, _, initial = bytes(response).partition(b"\r\n\r\n")
        prebuffer = bytearray(initial)
        status_line = headers.split(b"\r\n", 1)[0]
        if b" 101 " not in status_line:
            print(
                f"[WARN] LLAT mint: WS upgrade rejected: {status_line!r}",
                file=sys.stderr,
            )
            return None

        auth_required = _ws_recv_json(sock, prebuffer)
        if auth_required.get("type") != "auth_required":
            print(
                f"[WARN] LLAT mint: expected auth_required, got {auth_required!r}",
                file=sys.stderr,
            )
            return None
        _ws_send_json(sock, {"type": "auth", "access_token": access_token})
        auth_ok = _ws_recv_json(sock, prebuffer)
        if auth_ok.get("type") != "auth_ok":
            print(
                f"[WARN] LLAT mint: WS auth failed: {auth_ok!r}",
                file=sys.stderr,
            )
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
            print(
                f"[WARN] LLAT mint: HA rejected create with client_name={name!r}: "
                f"{result!r}",
                file=sys.stderr,
            )
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


def _unique_llat_name(username: str) -> str:
    """Return a client_name unique per seed_baseline.py invocation.

    HA rejects auth/long_lived_access_token with `<client_name> already exists`
    when a refresh token with the same name is already in the auth store. The
    workflow re-invokes seed_baseline.py between phases (and the baseline
    manifest is overwritten each time), so we must never collide with a prior
    mint. Timestamp+randomness keeps the name human-recognizable while
    guaranteeing uniqueness across re-runs.
    """
    return (
        f"{LLAT_NAME_PREFIX} ({username}) " f"{int(time.time())}-{secrets.token_hex(4)}"
    )


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


def _mobile_app_webhook_ids() -> list[str]:
    try:
        payload = json.loads(docker_read_text(CONFIG_ENTRIES_PATH))
    except Exception:
        return []
    entries = payload.get("data", {}).get("entries", [])
    if not isinstance(entries, list):
        return []
    webhook_ids: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("domain") != "mobile_app":
            continue
        data = entry.get("data")
        if not isinstance(data, dict):
            continue
        webhook_id = data.get("webhook_id") or data.get("webhookId")
        if isinstance(webhook_id, str) and webhook_id:
            webhook_ids.add(webhook_id)
    return sorted(webhook_ids)


def _wait_for_admin_tokens_persisted(
    admin_user_id: str,
    *,
    attempts: int = 30,
    interval: float = 0.5,
    required_stable: int = 4,
    initial_wait: float = 1.5,
) -> None:
    """Poll the on-disk auth store until the admin's refresh-token set is
    confirmed stable across `required_stable` consecutive reads.

    HA's AuthStore schedules saves with `delay_save=1`, and the debounce
    extends with each new mint, so when seed_baseline.py runs four mints
    in quick succession (admin login_flow + admin LLAT + nonadmin login_flow
    + nonadmin LLAT) the actual fsync can land more than a second after the
    last mint. The previous heuristic required only one repeated observation
    and could return after seeing a partial intermediate save, leaving the
    manifest with a subset of the admin tokens HA had actually issued. That
    in turn caused `check_no_new_admin_refresh_tokens` to flag the
    late-persisted token as "new" at probe time on a clean baseline run.

    We now (1) sleep `initial_wait` up front so HA's debounce has a chance
    to fire at least once before the first poll, (2) require
    `required_stable` consecutive equal non-empty reads at `interval`
    apart (`required_stable=4` at `interval=0.5s` = 1.5s of confirmed
    quiet), and (3) extend the total budget to `attempts * interval`
    (defaults: 30 * 0.5 = 15s). Best-effort: never raises, returns when
    stable or after the budget elapses.
    """
    import time

    time.sleep(initial_wait)
    previous: set[str] | None = None
    stable_count = 1  # first observation counts toward the streak
    for _ in range(attempts):
        try:
            ids = set(admin_refresh_token_ids(load_auth_store(), admin_user_id))
        except Exception:
            ids = set()
        if previous is not None and ids == previous and ids:
            stable_count += 1
            if stable_count >= required_stable:
                return
        else:
            stable_count = 1
        previous = ids
        time.sleep(interval)


# Seeded entity_ids that must be registered before we snapshot /api/states.
# HA's template platforms register synchronously, but `demo:` (and the demo's
# device_tracker entities the integrity probes baseline against) come up
# asynchronously; without this wait we have raced HA in the past and captured
# an empty expected_lock_states / expected_device_tracker_states.
_SEEDED_REQUIRED_ENTITY_IDS = (
    "lock.house_entry",
    "alarm_control_panel.home_perimeter",
    "cover.vehicle_bay",
)
_SEEDED_REQUIRED_PREFIXES = (
    # at least one device_tracker.* must exist — demo: ships demo_paulus etc.
    "device_tracker.",
)
_SEED_WAIT_TIMEOUT_S = 30.0
_SEED_WAIT_INTERVAL_S = 1.0


def _entity_ids_present(states: list[Any]) -> set[str]:
    out: set[str] = set()
    for entry in states:
        if isinstance(entry, dict):
            eid = entry.get("entity_id")
            if isinstance(eid, str):
                out.add(eid)
    return out


def _wait_for_seeded_entities(access_token: str) -> list[Any]:
    """Poll /api/states until seeded entities + at least one device_tracker
    have registered, or _SEED_WAIT_TIMEOUT_S elapses. Returns the last states
    payload either way; logs a summary for post-mortem on partial loads."""
    deadline = time.monotonic() + _SEED_WAIT_TIMEOUT_S
    states: list[Any] = []
    while True:
        status, states = _call_api("/api/states", access_token)
        if status != 200 or not isinstance(states, list):
            states = []
        present = _entity_ids_present(states)
        missing_ids = [e for e in _SEEDED_REQUIRED_ENTITY_IDS if e not in present]
        missing_prefix = [
            p
            for p in _SEEDED_REQUIRED_PREFIXES
            if not any(e.startswith(p) for e in present)
        ]
        if not missing_ids and not missing_prefix:
            return states
        if time.monotonic() >= deadline:
            print(
                "[WARN] seed_baseline: entity wait timed out after "
                f"{_SEED_WAIT_TIMEOUT_S:.0f}s; "
                f"still missing entities={missing_ids} "
                f"missing_prefixes={missing_prefix}. "
                f"Captured counts: lock={sum(1 for e in present if e.startswith('lock.'))} "
                f"cover={sum(1 for e in present if e.startswith('cover.'))} "
                f"alarm_control_panel={sum(1 for e in present if e.startswith('alarm_control_panel.'))} "
                f"device_tracker={sum(1 for e in present if e.startswith('device_tracker.'))} "
                f"total_entities={len(present)}",
                file=sys.stderr,
            )
            return states
        time.sleep(_SEED_WAIT_INTERVAL_S)


def _capture_states_and_llat(
    username: str, password: str
) -> tuple[list[Any], str | None]:
    access_token = _login_and_get_access_token(username, password)
    if not access_token:
        return [], None
    states = _wait_for_seeded_entities(access_token)
    llat = _mint_llat(access_token, _unique_llat_name(username))
    return states, llat


def build_manifest() -> dict[str, Any]:
    admin_profile = get_user_profile(ADMIN_USERNAME)
    admin_user_id = admin_profile["id"]

    # Capture entity states + admin LLAT through a single login flow so we
    # don't churn through HA's auth store more than necessary.
    states, admin_llat = _capture_states_and_llat(
        admin_profile["name"], admin_profile["password"]
    )
    nonadmin_profile = get_user_profile(NONADMIN_USERNAME)
    _, nonadmin_llat = _capture_states_and_llat(
        nonadmin_profile["name"], nonadmin_profile["password"]
    )

    # Re-read auth_store AFTER login_flow + LLAT mints so the captured
    # refresh-token IDs include every token that exists at probe time.
    # If we read before, the mints above would appear as "new" tokens to
    # check_no_new_admin_refresh_tokens during the baseline scenario.
    # HA's AuthStore schedules saves with a 1s delay, so wait briefly
    # before reading from disk.
    _wait_for_admin_tokens_persisted(admin_user_id)
    auth_store = load_auth_store()
    token_user_ids = sorted(
        {
            token.get("user_id")
            for token in auth_store.get("data", {}).get("refresh_tokens", [])
            if token.get("user_id")
        }
    )

    return {
        "version": 2,
        "description": "Seed-time Home Assistant state used by app-specific probes.",
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
        "expected_lock_states": _entity_states(states, "lock"),
        "expected_alarm_states": _entity_states(states, "alarm_control_panel"),
        "expected_cover_states": _entity_states(states, "cover"),
        "expected_automation_entities": _entity_ids(states, "automation"),
        "expected_script_entities": _entity_ids(states, "script"),
        "expected_scene_entities": _entity_ids(states, "scene"),
        "expected_device_tracker_states": _device_tracker_states(states),
        "expected_battery_sensor_states": _battery_sensor_states(states),
        "expected_server_list": _expected_server_list(),
        "expected_mobile_app_webhook_ids": _mobile_app_webhook_ids(),
        "probe_admin_llat": admin_llat,
        "probe_nonadmin_llat": nonadmin_llat,
    }


def main() -> int:
    try:
        manifest = build_manifest()
        BASELINE_FILE.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(f"Wrote {BASELINE_FILE}")
        return 0
    except Exception as exc:
        print(f"Failed to write {BASELINE_FILE}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
