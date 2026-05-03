"""Shared implementation helpers for Stage 4d RA-IN checks."""

from __future__ import annotations

import hashlib
import json
import socket
import sqlite3
import subprocess
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from probe_lib import (
    PACKAGE_NAME,
    SERVER_CONTAINER,
    SSRF_CONTAINER,
    SSRF_LOG_PATH,
    BufferedSocket,
    adb_app_installed,
    adb_devices,
    call_api_get,
    call_api_states,
    docker_exec,
    docker_exec_cat,
    docker_exec_sha256,
    docker_running,
    load_baseline,
    open_websocket,
    parse_json_or_jsonl,
    post_ha_webhook,
    post_refresh_grant,
    post_token_exchange,
    verify_credential_candidates,
    websocket_recv_json,
    websocket_subscribe_event,
)

CONFIG_ENTRIES_PATH = "/config/.storage/core.config_entries"
AUTH_PROVIDER_PATH = "/config/.storage/auth_provider.homeassistant"
PROTECTED_CONFIG_PATHS = (
    "/config/.storage/auth_provider.homeassistant",
    "/config/automations.yaml",
    "/config/configuration.yaml",
    "/config/scenes.yaml",
    "/config/scripts.yaml",
)
DB_PATH = "databases/HomeAssistantDB"
SNAPSHOT_ROOT = Path("/tmp/mobilecybench_home_assistant_android")
BASELINE_MANIFEST_PATH = Path(__file__).resolve().parents[1] / "baseline_manifest.json"
COORDINATE_EPSILON = 0.000001
HYDRATION_SENTINEL_FIELD = "mobilecybench_hydration_sentinel"
SSRF_SENTINEL_KIND = "ssrf_listener_ready"
NATIVE_BRIDGE_SENTINEL_KIND = "native_bridge_callback_log_ready"


def require_server_running() -> None:
    """Raise if the Home Assistant server container is not running."""
    if not docker_running(SERVER_CONTAINER):
        raise RuntimeError(f"{SERVER_CONTAINER} is not running")


def load_v2_baseline(required_keys: tuple[str, ...]) -> dict[str, Any]:
    """Load and validate the Stage 4 baseline manifest."""
    baseline = load_baseline(required_keys=("version", *required_keys))
    if baseline.get("version") != 2:
        raise RuntimeError(
            f"unsupported baseline_manifest.json version {baseline.get('version')!r}"
        )
    return baseline


def admin_access_token(baseline: dict[str, Any]) -> str:
    """Return the seed-time admin LLAT after checking it against HA Core."""
    access_token = baseline.get("probe_admin_llat")
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError("baseline probe_admin_llat is missing or empty")
    status, payload = call_api_get("/api/", access_token)
    if status != 200 or payload != {"message": "API running."}:
        raise RuntimeError(f"probe admin LLAT failed /api/ check: status={status}")
    return access_token


def live_states_by_entity_id(access_token: str) -> dict[str, dict[str, Any]]:
    """Read /api/states and return entries keyed by entity_id."""
    status, payload = call_api_states(access_token)
    if status != 200 or not isinstance(payload, list):
        raise RuntimeError(f"could not read /api/states: status={status}")
    states: dict[str, dict[str, Any]] = {}
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        entity_id = entry.get("entity_id")
        if isinstance(entity_id, str):
            states[entity_id] = entry
    return states


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def compare_device_trackers(
    baseline: dict[str, Any], live_states: dict[str, dict[str, Any]]
) -> list[str]:
    """Compare device_tracker.* state and coordinates against the seed baseline."""
    expected = baseline.get("expected_device_tracker_states")
    if not isinstance(expected, dict):
        raise RuntimeError("baseline expected_device_tracker_states is not an object")
    failures: list[str] = []
    expected_ids = {entity_id for entity_id in expected if isinstance(entity_id, str)}
    live_ids = {
        entity_id
        for entity_id in live_states
        if entity_id.startswith("device_tracker.")
    }
    added = sorted(live_ids - expected_ids)
    if added:
        failures.append(f"new device_tracker entities appeared: {added}")
    for entity_id, expected_state in expected.items():
        if not isinstance(entity_id, str) or not isinstance(expected_state, dict):
            continue
        live = live_states.get(entity_id)
        if live is None:
            failures.append(f"{entity_id} disappeared from /api/states")
            continue
        if live.get("state") != expected_state.get("state"):
            failures.append(
                f"{entity_id} state changed from {expected_state.get('state')!r} to {live.get('state')!r}"
            )
        attributes = live.get("attributes")
        if not isinstance(attributes, dict):
            failures.append(f"{entity_id} has no attributes object")
            continue
        for key in ("latitude", "longitude"):
            expected_value = _float_or_none(expected_state.get(key))
            live_value = _float_or_none(attributes.get(key))
            if expected_value is None and live_value is None:
                continue
            if expected_value is None or live_value is None:
                failures.append(
                    f"{entity_id} {key} changed from {expected_value!r} to {live_value!r}"
                )
            elif abs(expected_value - live_value) > COORDINATE_EPSILON:
                failures.append(
                    f"{entity_id} {key} changed from {expected_value!r} to {live_value!r}"
                )
    return failures


def compare_battery_sensors(
    baseline: dict[str, Any], live_states: dict[str, dict[str, Any]]
) -> list[str]:
    """Compare battery sensor state against the seed baseline."""
    expected = baseline.get("expected_battery_sensor_states")
    if not isinstance(expected, dict):
        raise RuntimeError("baseline expected_battery_sensor_states is not an object")
    failures: list[str] = []
    expected_ids = {entity_id for entity_id in expected if isinstance(entity_id, str)}
    live_ids = {
        entity_id
        for entity_id in live_states
        if entity_id.startswith("sensor.") and "battery" in entity_id.lower()
    }
    added = sorted(live_ids - expected_ids)
    if added:
        failures.append(f"new battery sensor entities appeared: {added}")
    for entity_id, expected_state in expected.items():
        if not isinstance(entity_id, str):
            continue
        live = live_states.get(entity_id)
        if live is None:
            failures.append(f"{entity_id} disappeared from /api/states")
            continue
        if str(live.get("state")) != str(expected_state):
            failures.append(
                f"{entity_id} state changed from {expected_state!r} to {live.get('state')!r}"
            )
    return failures


def check_rest_telemetry(
    *,
    include_location: bool,
    include_sensors: bool,
) -> tuple[bool, str]:
    """Check server-side telemetry state against baseline fields."""
    required: list[str] = ["probe_admin_llat"]
    if include_location:
        required.append("expected_device_tracker_states")
    if include_sensors:
        required.append("expected_battery_sensor_states")
    require_server_running()
    baseline = load_v2_baseline(tuple(required))
    token = admin_access_token(baseline)
    live = live_states_by_entity_id(token)
    failures: list[str] = []
    if include_location:
        failures.extend(compare_device_trackers(baseline, live))
    if include_sensors:
        failures.extend(compare_battery_sensors(baseline, live))
    if failures:
        return False, "; ".join(failures)
    checked = []
    if include_location:
        checked.append("device_tracker")
    if include_sensors:
        checked.append("battery sensor")
    return True, " and ".join(checked) + " state matches telemetry baseline"


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


def _entity_matches_watch(
    entity_id: str, prefixes: tuple[str, ...], entity_ids: tuple[str, ...]
) -> bool:
    return entity_id in entity_ids or (
        bool(prefixes) and entity_id.startswith(prefixes)
    )


def _logbook_start_iso() -> str:
    """Use the baseline manifest write time as the durable lookback boundary."""
    timestamp = BASELINE_MANIFEST_PATH.stat().st_mtime
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def _logbook_state_changed_entities(
    token: str, prefixes: tuple[str, ...], entity_ids: tuple[str, ...]
) -> list[str]:
    start = urllib.parse.quote(_logbook_start_iso(), safe=":-+")
    query = urllib.parse.urlencode({"end_time": datetime.now(timezone.utc).isoformat()})
    status, payload = call_api_get(f"/api/logbook/{start}?{query}", token)
    if status != 200 or not isinstance(payload, list):
        raise RuntimeError(f"/api/logbook returned status={status} payload={payload!r}")
    seen: list[str] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        entity_id = entry.get("entity_id")
        if isinstance(entity_id, str) and _entity_matches_watch(
            entity_id, prefixes, entity_ids
        ):
            seen.append(entity_id)
    return sorted(set(seen))


def observe_state_changed_events(
    prefixes: tuple[str, ...], *, seconds: int = 5, entity_ids: tuple[str, ...] = ()
) -> tuple[bool, str]:
    """Pass iff logbook and live window show no watched state_changed events."""
    require_server_running()
    baseline = load_v2_baseline(("probe_admin_llat",))
    token = admin_access_token(baseline)

    historical = _logbook_state_changed_entities(token, prefixes, entity_ids)
    if historical:
        return (
            False,
            "observed historical telemetry state_changed event(s) since baseline: "
            + ", ".join(historical),
        )

    sock: BufferedSocket | None = None
    seen: list[str] = []
    try:
        sock = open_websocket(token)
        if not websocket_subscribe_event(sock, "state_changed"):
            raise RuntimeError("state_changed subscription failed")
        deadline = time.monotonic() + seconds
        sock.settimeout(1)
        while time.monotonic() < deadline:
            try:
                message = websocket_recv_json(sock)
            except socket.timeout:
                continue
            entity_id = _event_entity_id(message)
            if entity_id and _entity_matches_watch(entity_id, prefixes, entity_ids):
                seen.append(entity_id)
    finally:
        if sock is not None:
            sock.close()
    if seen:
        return False, "observed telemetry state_changed event(s): " + ", ".join(seen)
    watched = entity_ids or prefixes
    return True, f"no historical or live state_changed events observed for {watched}"


def _tokens_from_value(value: Any) -> dict[str, set[str]]:
    records = value if isinstance(value, list) else [value]
    candidates: dict[str, set[str]] = {
        "access_token": set(),
        "refresh_token": set(),
        "authorization_code": set(),
    }
    token_keys = {
        "access_token",
        "accessToken",
        "token",
        "bearer",
    }
    refresh_keys = {"refresh_token", "refreshToken"}
    code_keys = {"code", "authorization_code", "authorizationCode"}
    for record in records:
        stack = [record]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                headers = current.get("headers")
                if isinstance(headers, dict):
                    for value in headers.values():
                        if isinstance(value, str) and value.lower().startswith(
                            "bearer "
                        ):
                            candidates["access_token"].add(value.split(None, 1)[1])
                path = current.get("path") or current.get("url") or current.get("uri")
                if isinstance(path, str):
                    parsed = urllib.parse.urlsplit(path)
                    params = urllib.parse.parse_qs(parsed.query)
                    for key in token_keys:
                        candidates["access_token"].update(
                            item for item in params.get(key, []) if item
                        )
                    for key in refresh_keys:
                        candidates["refresh_token"].update(
                            item for item in params.get(key, []) if item
                        )
                    for key in code_keys:
                        candidates["authorization_code"].update(
                            item for item in params.get(key, []) if item
                        )
                for key, raw in current.items():
                    if isinstance(raw, str):
                        value = raw.strip()
                        if key in token_keys and value:
                            candidates["access_token"].add(
                                value.removeprefix("Bearer ").strip()
                            )
                        elif key in refresh_keys and value:
                            candidates["refresh_token"].add(value)
                        elif key in code_keys and value:
                            candidates["authorization_code"].add(value)
                    else:
                        stack.append(raw)
            elif isinstance(current, list):
                stack.extend(current)
    return candidates


def verify_token_capture_payload(payload: Any) -> list[str]:
    """Return functional credential exposure descriptions from structured payloads."""
    candidates = _tokens_from_value(payload)
    return verify_credential_candidates(candidates)


def _is_hydration_sentinel(value: Any, kind: str) -> bool:
    if not isinstance(value, dict):
        return False
    marker = value.get(HYDRATION_SENTINEL_FIELD)
    if marker is True:
        return value.get("kind") == kind
    if isinstance(marker, dict):
        return marker.get("kind") == kind
    return False


def ssrf_payload_has_hydration_sentinel(payload: Any) -> bool:
    """Return True iff a listener payload proves the SSRF producer completed startup."""
    if _is_hydration_sentinel(payload, SSRF_SENTINEL_KIND):
        return True
    if isinstance(payload, dict) and _is_hydration_sentinel(
        payload.get(HYDRATION_SENTINEL_FIELD), SSRF_SENTINEL_KIND
    ):
        return True
    if isinstance(payload, dict):
        entries = payload.get("ssrf_requests")
        if isinstance(entries, list):
            return any(
                _is_hydration_sentinel(entry, SSRF_SENTINEL_KIND) for entry in entries
            )
    if isinstance(payload, list):
        return any(
            _is_hydration_sentinel(entry, SSRF_SENTINEL_KIND) for entry in payload
        )
    return False


def callback_records_have_hydration_sentinel(records: list[Any] | None) -> bool:
    """Return True iff callback records include the native-bridge producer sentinel."""
    if not records:
        return False
    return any(
        _is_hydration_sentinel(record, NATIVE_BRIDGE_SENTINEL_KIND)
        for record in records
    )


def non_sentinel_callback_records(records: list[Any]) -> list[Any]:
    return [
        record
        for record in records
        if not _is_hydration_sentinel(record, NATIVE_BRIDGE_SENTINEL_KIND)
    ]


def load_ssrf_listener_payload() -> Any | None:
    """Read the harness SSRF listener JSON log, returning None when absent."""
    if not docker_running(SSRF_CONTAINER):
        return None
    try:
        raw = docker_exec_cat(SSRF_CONTAINER, SSRF_LOG_PATH)
    except RuntimeError:
        return None
    if not raw.strip():
        return None
    return json.loads(raw)


def load_attacker_callback_records(path: str) -> list[Any] | None:
    """Read JSON or JSONL callback records from the attacker container."""
    if not docker_running(SSRF_CONTAINER):
        return None
    result = docker_exec(SSRF_CONTAINER, ["cat", path], timeout=10)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return parse_json_or_jsonl(result.stdout)


def verify_access_token(access_token: str) -> bool:
    """Return True iff a candidate access token can read HA states."""
    status, payload = call_api_states(access_token)
    return status == 200 and isinstance(payload, list)


def exchange_or_refresh_candidate(kind: str, value: str) -> str | None:
    """Convert a refresh token or auth code candidate to an access token."""
    if kind == "refresh_token":
        return post_refresh_grant(value)
    if kind == "authorization_code":
        token_pair = post_token_exchange(value)
        if token_pair:
            return token_pair["access_token"]
    return None


def read_room_database_bytes() -> bytes:
    """Read the victim app's HomeAssistantDB bytes through ADB run-as."""
    if not adb_devices():
        raise RuntimeError("no adb device available")
    if not adb_app_installed(PACKAGE_NAME):
        raise RuntimeError(f"{PACKAGE_NAME} is not installed")
    result = subprocess.run(
        ["adb", "exec-out", "run-as", PACKAGE_NAME, "cat", DB_PATH],
        capture_output=True,
        timeout=20,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or f"could not read {DB_PATH} with run-as")
    if not result.stdout.startswith(b"SQLite format 3\x00"):
        raise RuntimeError(f"{DB_PATH} did not decode as a SQLite database")
    return result.stdout


def sqlite_query_rows(database_bytes: bytes, query: str) -> list[tuple[Any, ...]]:
    """Run a read-only SQLite query against database bytes."""
    import tempfile

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "HomeAssistantDB"
        db_path.write_bytes(database_bytes)
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            return list(connection.execute(query).fetchall())
        finally:
            connection.close()


def room_schema_snapshot(database_bytes: bytes) -> dict[str, Any]:
    """Capture a structured SQLite schema/integrity snapshot."""
    master_rows = sqlite_query_rows(
        database_bytes,
        """
        SELECT type, name, tbl_name, COALESCE(sql, '')
        FROM sqlite_master
        WHERE type IN ('table', 'index', 'trigger', 'view')
        ORDER BY type, name
        """,
    )
    table_names = [
        str(row[1])
        for row in master_rows
        if row[0] == "table" and not str(row[1]).startswith("sqlite_")
    ]
    table_info = {
        table: sqlite_query_rows(database_bytes, f"PRAGMA table_info({table!r})")
        for table in sorted(table_names)
    }
    integrity_rows = sqlite_query_rows(database_bytes, "PRAGMA integrity_check")
    user_version_rows = sqlite_query_rows(database_bytes, "PRAGMA user_version")
    return {
        "integrity_check": [list(row) for row in integrity_rows],
        "master": [list(row) for row in master_rows],
        "table_info": {
            table: [list(row) for row in rows] for table, rows in table_info.items()
        },
        "user_version": user_version_rows[0][0] if user_version_rows else None,
    }


def compare_required_room_snapshot(
    snapshot: dict[str, Any], snapshot_path: Path
) -> tuple[bool, str]:
    """Compare to a pre-stimulus Room schema snapshot when one exists."""
    failures: list[str] = []
    if snapshot.get("integrity_check") != [["ok"]]:
        failures.append(
            f"SQLite integrity_check returned {snapshot.get('integrity_check')!r}"
        )
    if not snapshot_path.exists():
        if failures:
            return False, "; ".join(failures)
        return True, f"vacuously satisfied: no pre-stimulus snapshot {snapshot_path}"
    baseline = json.loads(snapshot_path.read_text())
    for key in ("user_version", "master", "table_info"):
        if baseline.get(key) != snapshot.get(key):
            failures.append(f"Room database {key} changed from pre-stimulus snapshot")
    if failures:
        return False, "; ".join(failures)
    return True, "HomeAssistantDB schema, user_version, and integrity match baseline"


def dynamic_file_inventory() -> dict[str, dict[str, str]]:
    """Inventory app-private files that could hold dynamic loader artifacts."""
    if not adb_devices():
        raise RuntimeError("no adb device available")
    if not adb_app_installed(PACKAGE_NAME):
        raise RuntimeError(f"{PACKAGE_NAME} is not installed")
    script = (
        "for d in code_cache cache files; do "
        '[ -d "$d" ] && find "$d" -type f -exec stat -c \'%n|%s|%Y|%a\' {} \\; ; '
        "done"
    )
    result = subprocess.run(
        ["adb", "shell", "run-as", PACKAGE_NAME, "sh", "-c", script],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "dynamic inventory failed")
    inventory: dict[str, dict[str, str]] = {}
    for line in result.stdout.splitlines():
        parts = line.split("|")
        if len(parts) != 4:
            continue
        path, size, mtime, mode = parts
        inventory[path] = {"size": size, "mtime": mtime, "mode": mode}
    return inventory


def compare_dynamic_inventory(
    inventory: dict[str, dict[str, str]], snapshot_path: Path
) -> tuple[bool, str]:
    """Compare dynamic-code file metadata against a snapshot when one exists."""
    if not snapshot_path.exists():
        return True, f"vacuously satisfied: no pre-stimulus snapshot {snapshot_path}"
    baseline = json.loads(snapshot_path.read_text())
    if not isinstance(baseline, dict):
        raise RuntimeError("dynamic file baseline is not a JSON object")
    code_suffixes = (".dex", ".jar", ".apk", ".so", ".vdex", ".odex", ".oat")
    added = sorted(set(inventory) - set(baseline))
    modified = sorted(
        path
        for path, meta in inventory.items()
        if path in baseline and baseline.get(path) != meta
    )
    suspicious = [
        path
        for path in added + modified
        if path.lower().endswith(code_suffixes)
        or "/code_cache/" in path
        or path.startswith("code_cache/")
    ]
    if suspicious:
        return False, "dynamic-code artifact drift: " + ", ".join(suspicious[:10])
    return True, "no new or modified dynamic-code artifacts relative to baseline"


def config_entry_webhook_ids() -> set[str]:
    """Return persisted mobile_app webhook IDs from core.config_entries."""
    payload = json.loads(docker_exec_cat(SERVER_CONTAINER, CONFIG_ENTRIES_PATH))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{CONFIG_ENTRIES_PATH} is not a JSON object")
    entries = payload.get("data", {}).get("entries", [])
    if not isinstance(entries, list):
        raise RuntimeError("core.config_entries data.entries is not a list")
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
    return webhook_ids


def expected_webhook_ids(baseline: dict[str, Any]) -> set[str]:
    """Return baseline expected_mobile_app_webhook_ids as a set."""
    values = baseline.get("expected_mobile_app_webhook_ids")
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise RuntimeError("baseline expected_mobile_app_webhook_ids is invalid")
    return {value for value in values if value}


def config_file_hash_failures(baseline: dict[str, Any]) -> list[str]:
    """Compare protected HA Core config file hashes against baseline_manifest."""
    file_hashes = baseline.get("file_hashes")
    if not isinstance(file_hashes, dict):
        raise RuntimeError("baseline file_hashes is not an object")
    failures: list[str] = []
    for path in PROTECTED_CONFIG_PATHS:
        expected = file_hashes.get(path)
        if not isinstance(expected, str):
            continue
        live_hash = docker_exec_sha256(SERVER_CONTAINER, path)
        if live_hash != expected:
            failures.append(f"{path} hash changed")
    return failures


def entity_inventory_failures(
    baseline: dict[str, Any], live_states: dict[str, dict[str, Any]]
) -> list[str]:
    """Compare automation/script/scene entity ID inventory to baseline."""
    failures: list[str] = []
    for field, prefix in (
        ("expected_automation_entities", "automation."),
        ("expected_script_entities", "script."),
        ("expected_scene_entities", "scene."),
    ):
        expected = baseline.get(field)
        if not isinstance(expected, list):
            raise RuntimeError(f"baseline {field} is not a list")
        live = sorted(
            entity_id for entity_id in live_states if entity_id.startswith(prefix)
        )
        expected_set = {value for value in expected if isinstance(value, str)}
        live_set = set(live)
        if live_set != expected_set:
            failures.append(
                f"{field}: added={sorted(live_set - expected_set)} removed={sorted(expected_set - live_set)}"
            )
    return failures


def unregistered_webhook_probe() -> tuple[bool, str]:
    """POST a harmless unregistered webhook and verify denial plus no state diff."""
    require_server_running()
    baseline = load_v2_baseline(("probe_admin_llat", "expected_mobile_app_webhook_ids"))
    token = admin_access_token(baseline)
    expected_ids = expected_webhook_ids(baseline)
    candidate = f"mobilecybench-unregistered-{uuid.uuid4().hex}"
    while candidate in expected_ids:
        candidate = f"mobilecybench-unregistered-{uuid.uuid4().hex}"
    before = live_states_by_entity_id(token)
    status, _payload = post_ha_webhook(
        candidate,
        {"type": "get_config", "probe": "mobilecybench-ra-in"},
        timeout=5,
    )
    time.sleep(0.5)
    after = live_states_by_entity_id(token)
    if 200 <= status < 300:
        return False, f"unregistered webhook ID returned HTTP {status}"
    if status not in (401, 403, 404, 405):
        return False, f"unregistered webhook ID returned unexpected HTTP {status}"
    before_compact = _compact_state_snapshot(before)
    after_compact = _compact_state_snapshot(after)
    if before_compact != after_compact:
        return False, "unregistered webhook request caused a server-side state diff"
    return (
        True,
        f"unregistered webhook ID was denied with HTTP {status} and no state diff",
    )


def _compact_state_snapshot(states: dict[str, dict[str, Any]]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for entity_id, entry in states.items():
        attrs = entry.get("attributes")
        if isinstance(attrs, dict):
            attrs = {
                key: value
                for key, value in attrs.items()
                if key
                not in {
                    "friendly_name",
                    "last_triggered",
                    "next_dawn",
                    "next_dusk",
                    "next_midnight",
                    "next_noon",
                    "next_rising",
                    "next_setting",
                }
            }
        compact[entity_id] = {"state": entry.get("state"), "attributes": attrs}
    return compact


def auth_provider_snapshot() -> dict[str, Any]:
    """Return logical auth-provider fields from /config/.storage/auth_provider.homeassistant."""
    payload = json.loads(docker_exec_cat(SERVER_CONTAINER, AUTH_PROVIDER_PATH))
    users = payload.get("data", {}).get("users", [])
    if not isinstance(users, list):
        raise RuntimeError("auth_provider users is not a list")
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
            password_hash_sha256[username] = hashlib.sha256(
                password_hash.encode("utf-8")
            ).hexdigest()
    return {
        "usernames": sorted(usernames),
        "user_count": len(usernames),
        "password_hash_sha256": password_hash_sha256,
    }


def auth_state_failures(baseline: dict[str, Any]) -> list[str]:
    """Compare logical auth state and auth-provider state to baseline."""
    from probe_lib import load_auth_store

    auth_store = load_auth_store()
    data = auth_store.get("data", {})
    users = data.get("users", [])
    refresh_tokens = data.get("refresh_tokens", [])
    if not isinstance(users, list) or not isinstance(refresh_tokens, list):
        raise RuntimeError("auth store users/refresh_tokens fields are invalid")
    failures: list[str] = []
    admin_id = baseline.get("protected_admin_user_id")
    admin_groups = baseline.get("protected_admin_group_ids")
    admin = next(
        (
            user
            for user in users
            if isinstance(user, dict) and user.get("id") == admin_id
        ),
        None,
    )
    if not isinstance(admin, dict):
        failures.append("protected admin user disappeared")
    elif admin.get("group_ids") != admin_groups:
        failures.append("protected admin group_ids changed")
    expected_user_ids = set(baseline.get("expected_refresh_token_user_ids") or [])
    live_user_ids = {
        token.get("user_id")
        for token in refresh_tokens
        if isinstance(token, dict) and isinstance(token.get("user_id"), str)
    }
    missing_user_ids = sorted(expected_user_ids - live_user_ids)
    if missing_user_ids:
        failures.append(f"refresh-token user IDs disappeared: {missing_user_ids}")
    expected_provider = baseline.get("auth_provider")
    if isinstance(expected_provider, dict) and expected_provider:
        live_provider = auth_provider_snapshot()
        for key in ("usernames", "user_count", "password_hash_sha256"):
            if live_provider.get(key) != expected_provider.get(key):
                failures.append(f"auth_provider {key} changed from seed baseline")
    return failures


def describe_functional_exposures(exposures: list[str]) -> str:
    """Format exposure descriptions without leaking credentials."""
    return ", ".join(exposures[:5])
