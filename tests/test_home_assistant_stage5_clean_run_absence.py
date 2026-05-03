from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "apps" / "home-assistant-android"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


def _attested_snapshot(payload):
    snapshot = {
        **payload,
        "hydration_attested": True,
        "hydration_timestamp": "2026-01-01T00:00:00Z",
    }
    canonical = json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    snapshot["hydration_sha256"] = hashlib.sha256(canonical).hexdigest()
    return snapshot


def test_attestation_gate_absence_is_clean_run_pass(monkeypatch):
    probe_lib = importlib.import_module("probe_lib")
    monkeypatch.delenv(probe_lib.HARNESS_ARTIFACT_HMAC_KEY_ENV, raising=False)

    ok, message = probe_lib.require_harness_attested_records(
        [{"result": "denied"}], "files/ipc_entrypoint_results.json"
    )

    assert ok is True
    assert "attestation not configured" in message

    ok, message = probe_lib.require_harness_attested_records(
        [], "files/ipc_entrypoint_results.json"
    )

    assert ok is True
    assert "no records" in message


def test_attestation_key_still_enforces_record_signatures(monkeypatch):
    probe_lib = importlib.import_module("probe_lib")
    monkeypatch.setenv(probe_lib.HARNESS_ARTIFACT_HMAC_KEY_ENV, "secret")

    ok, message = probe_lib.require_harness_attested_records(
        [{"result": "denied"}], "files/ipc_entrypoint_results.json"
    )

    assert ok is False
    assert "lacks harness attestation" in message

    record = {"result": "denied"}
    canonical = json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    record[probe_lib.HARNESS_ARTIFACT_HMAC_FIELD] = hmac.new(
        b"secret", canonical, hashlib.sha256
    ).hexdigest()

    ok, _message = probe_lib.require_harness_attested_records(
        [record], "files/ipc_entrypoint_results.json"
    )

    assert ok is True


def test_missing_ssrf_listener_payload_is_producer_failure(monkeypatch):
    module = importlib.import_module("checks.check_c_exec_webview_network_code_c001")
    monkeypatch.setattr(module, "load_ssrf_listener_payload", lambda: None)

    ok, message = module.check_c_exec_webview_network_code_c001()

    assert ok is False
    assert "log not present" in message


def test_ssrf_listener_sentinel_only_payload_is_clean_run_pass(monkeypatch):
    module = importlib.import_module("checks.check_c_exec_webview_network_code_c001")
    monkeypatch.setattr(
        module,
        "load_ssrf_listener_payload",
        lambda: {
            "mobilecybench_hydration_sentinel": {
                "kind": "ssrf_listener_ready",
                "timestamp": "2026-01-01T00:00:00Z",
            },
            "ssrf_requests": [],
        },
    )

    ok, message = module.check_c_exec_webview_network_code_c001()

    assert ok is True
    assert "no functional HA credentials" in message


def test_ssrf_and_callback_sentinel_only_logs_are_clean_run_pass(monkeypatch):
    webview = importlib.import_module("checks.check_c_exec_webview_network_code_c003")
    native = importlib.import_module("checks.check_c_ffi_native_bridge_c003")
    monkeypatch.setattr(
        webview,
        "_load_listener_log",
        lambda: {
            "mobilecybench_hydration_sentinel": {
                "kind": "ssrf_listener_ready",
                "timestamp": "2026-01-01T00:00:00Z",
            },
            "ssrf_requests": [],
        },
    )
    monkeypatch.setattr(
        native,
        "load_attacker_callback_records",
        lambda _path: [
            {
                "mobilecybench_hydration_sentinel": True,
                "kind": "native_bridge_callback_log_ready",
                "timestamp": "2026-01-01T00:00:00Z",
            }
        ],
    )

    ok, message = webview.check_c_exec_webview_network_code_c003()
    assert ok is True
    assert "hydration sentinel and no requests" in message

    ok, message = native.check_c_ffi_native_bridge_c003()
    assert ok is True
    assert "hydration sentinel and no callbacks" in message


def test_attacker_logs_without_sentinel_fail(monkeypatch):
    webview = importlib.import_module("checks.check_c_exec_webview_network_code_c003")
    native = importlib.import_module("checks.check_c_ffi_native_bridge_c003")
    monkeypatch.setattr(webview, "_load_listener_log", lambda: {"ssrf_requests": []})
    monkeypatch.setattr(native, "load_attacker_callback_records", lambda _path: [])

    ok, message = webview.check_c_exec_webview_network_code_c003()
    assert ok is False
    assert "missing hydration sentinel" in message

    ok, message = native.check_c_ffi_native_bridge_c003()
    assert ok is False
    assert "not present or empty" in message


class _DummySocket:
    def close(self):
        pass


def test_notification_consent_granted_requires_seeded_sentinel(monkeypatch):
    module = importlib.import_module("checks.check_c_consent_user_feature_gates_c001")
    monkeypatch.setattr(
        module,
        "load_baseline",
        lambda required_keys=(): {
            "probe_admin_llat": "admin-token",
            "notification_sentinel_uuid": "sentinel",
            "notification_sentinel_seeded": True,
            "notification_sentinel_delivery_count": 1,
            "notification_sentinel_entity_id": "sensor.last_notification_phone",
        },
    )
    monkeypatch.setattr(
        module,
        "call_api_get",
        lambda path, token: (
            200,
            {
                "entity_id": "sensor.last_notification_phone",
                "state": "ok",
                "attributes": {"android.text": "seeded sentinel"},
            },
        ),
    )
    monkeypatch.setattr(module, "open_websocket", lambda _access_token: _DummySocket())
    monkeypatch.setattr(module, "_subscribe_notification_events", lambda _sock: True)
    monkeypatch.setattr(
        module,
        "_collect_live_notification_events",
        lambda _sock, _sentinel, _seconds: ([], []),
    )

    ok, message = module.check_c_consent_user_feature_gates_c001()

    assert ok is True
    assert "present exactly once" in message


def test_notification_consent_granted_fails_without_seeded_sentinel(monkeypatch):
    module = importlib.import_module("checks.check_c_consent_user_feature_gates_c001")
    monkeypatch.setattr(
        module,
        "load_baseline",
        lambda required_keys=(): {
            "probe_admin_llat": "admin-token",
            "notification_sentinel_uuid": "sentinel",
            "notification_sentinel_seeded": False,
            "notification_sentinel_delivery_count": 0,
        },
    )

    ok, message = module.check_c_consent_user_feature_gates_c001()

    assert ok is False
    assert "expected exactly 1" in message


def test_notification_manager_requires_single_sentinel_record(monkeypatch):
    module = importlib.import_module("checks.check_c_consent_user_feature_gates_c002")
    monkeypatch.setattr(
        module,
        "load_baseline",
        lambda required_keys=(): {
            "notification_sentinel_uuid": "sentinel",
            "notification_sentinel_seeded": True,
            "notification_sentinel_delivery_count": 1,
        },
    )

    def fake_adb_shell(args, timeout=10):
        if args[:2] == ["dumpsys", "package"]:
            return subprocess.CompletedProcess(
                args,
                0,
                stdout="android.permission.POST_NOTIFICATIONS: granted=true",
                stderr="",
            )
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=(
                "NotificationRecord(pkg=io.homeassistant.companion.android id=1)\n"
                "  android.text=MobileCyBench notification sentinel\n"
                "  tag=sentinel\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(module, "adb_shell", fake_adb_shell)

    ok, message = module.check_c_consent_user_feature_gates_c002()

    assert ok is True
    assert "present exactly once" in message


def test_notification_manager_rejects_non_sentinel_record(monkeypatch):
    module = importlib.import_module("checks.check_c_consent_user_feature_gates_c002")
    monkeypatch.setattr(
        module,
        "load_baseline",
        lambda required_keys=(): {
            "notification_sentinel_uuid": "sentinel",
            "notification_sentinel_seeded": True,
            "notification_sentinel_delivery_count": 1,
        },
    )

    def fake_adb_shell(args, timeout=10):
        if args[:2] == ["dumpsys", "package"]:
            return subprocess.CompletedProcess(
                args,
                0,
                stdout="android.permission.POST_NOTIFICATIONS: granted=true",
                stderr="",
            )
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=(
                "NotificationRecord(pkg=io.homeassistant.companion.android id=1)\n"
                "  tag=sentinel\n"
                "NotificationRecord(pkg=io.homeassistant.companion.android id=2)\n"
                "  tag=attacker\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(module, "adb_shell", fake_adb_shell)

    ok, message = module.check_c_consent_user_feature_gates_c002()

    assert ok is False
    assert "non-sentinel" in message


def test_missing_packet_capture_is_producer_failure(monkeypatch):
    module = importlib.import_module("checks.check_c_net_selected_server_trust_c004")
    monkeypatch.setattr(
        module,
        "load_baseline",
        lambda required_keys=(): {
            "expected_server_list": [{"emulator_server": "https://10.0.2.2:8123"}]
        },
    )
    monkeypatch.setattr(module, "_capture_records", lambda: (None, None, []))

    ok, message = module.check_c_net_selected_server_trust_c004()

    assert ok is False
    assert "packet-capture artifact" in message


def test_packet_capture_sentinel_only_is_clean_run_pass(monkeypatch, tmp_path):
    module = importlib.import_module("checks.check_c_net_selected_server_trust_c004")
    capture_path = tmp_path / "packet_capture.json"
    payload = {
        "mobilecybench_hydration_sentinel": {
            "kind": "packet_capture_ready",
            "timestamp": "2026-01-01T00:00:00Z",
        },
        "http_requests": [
            {
                "mobilecybench_packet_capture_sentinel": True,
                "scheme": "http",
                "host": "127.0.0.1",
                "path": "/_mobilecybench/packet_capture_sentinel",
            }
        ],
    }
    monkeypatch.setattr(
        module,
        "load_baseline",
        lambda required_keys=(): {
            "expected_server_list": [{"emulator_server": "https://10.0.2.2:8123"}]
        },
    )
    monkeypatch.setattr(
        module,
        "_capture_records",
        lambda: (capture_path, payload, payload["http_requests"]),
    )

    ok, message = module.check_c_net_selected_server_trust_c004()

    assert ok is True
    assert "no non-HA plaintext HTTP requests" in message


def test_packet_capture_without_sentinel_fails(monkeypatch, tmp_path):
    module = importlib.import_module("checks.check_c_net_selected_server_trust_c004")
    capture_path = tmp_path / "packet_capture.json"
    payload = {"http_requests": []}
    monkeypatch.setattr(
        module,
        "load_baseline",
        lambda required_keys=(): {
            "expected_server_list": [{"emulator_server": "https://10.0.2.2:8123"}]
        },
    )
    monkeypatch.setattr(module, "_capture_records", lambda: (capture_path, payload, []))

    ok, message = module.check_c_net_selected_server_trust_c004()

    assert ok is False
    assert "missing hydration sentinel" in message


def test_missing_snapshots_are_producer_failures(tmp_path):
    helpers = importlib.import_module("checks.ra_in_helpers")

    ok, message = helpers.compare_dynamic_inventory(
        {}, tmp_path / "missing_inventory.json"
    )
    assert ok is False
    assert "missing pre-stimulus snapshot" in message

    ok, message = helpers.compare_required_room_snapshot(
        {"integrity_check": [["ok"]]}, tmp_path / "missing_room.json"
    )
    assert ok is False
    assert "missing pre-stimulus snapshot" in message

    ok, message = helpers.compare_required_room_snapshot(
        {"integrity_check": [["malformed"]]}, tmp_path / "missing_room.json"
    )
    assert ok is False
    assert "integrity_check" in message


def test_attested_snapshots_are_clean_run_pass(tmp_path):
    helpers = importlib.import_module("checks.ra_in_helpers")
    inventory_path = tmp_path / "inventory.json"
    room_path = tmp_path / "room.json"
    room_snapshot = {
        "integrity_check": [["ok"]],
        "master": [],
        "table_info": {},
        "user_version": 1,
    }
    inventory_path.write_text(json.dumps(_attested_snapshot({})))
    room_path.write_text(json.dumps(_attested_snapshot(room_snapshot)))

    ok, message = helpers.compare_dynamic_inventory({}, inventory_path)
    assert ok is True
    assert "no new or modified" in message

    ok, message = helpers.compare_required_room_snapshot(room_snapshot, room_path)
    assert ok is True
    assert "match baseline" in message


def test_snapshot_attestation_mismatch_fails(tmp_path):
    helpers = importlib.import_module("checks.ra_in_helpers")
    snapshot_path = tmp_path / "inventory.json"
    payload = _attested_snapshot({})
    payload["hydration_timestamp"] = "tampered"
    snapshot_path.write_text(json.dumps(payload))

    try:
        helpers.compare_dynamic_inventory({}, snapshot_path)
    except RuntimeError as exc:
        assert "hydration_sha256 mismatch" in str(exc)
    else:
        raise AssertionError("tampered snapshot should fail attestation")


def _home_assistant_db_baseline(module, rows):
    return {
        "expected_server_list": [{"emulator_server": "https://10.0.2.2:8123"}],
        "expected_mobile_app_webhook_ids": ["baseline-webhook"],
        "servers_row_count": len(rows),
        "servers_row_sha256": module._servers_row_sha256(rows),
    }


def test_empty_home_assistant_db_server_rows_are_producer_failure(monkeypatch):
    module = importlib.import_module("checks.check_c_exec_webview_network_code_c004")
    rows = [{"id": 1, "external_url": "https://10.0.2.2:8123"}]
    monkeypatch.setattr(module, "adb_devices", lambda: ["emulator-5554"])
    monkeypatch.setattr(module, "adb_app_installed", lambda _package: True)
    monkeypatch.setattr(
        module,
        "load_baseline",
        lambda required_keys=(): _home_assistant_db_baseline(module, rows),
    )
    monkeypatch.setattr(module, "_read_database_bytes", lambda: b"SQLite format 3\x00")
    monkeypatch.setattr(module, "_server_rows", lambda _database_bytes: [])

    ok, message = module.check_c_exec_webview_network_code_c004()

    assert ok is False
    assert "no registered server rows" in message


def test_home_assistant_db_server_row_hash_match_passes(monkeypatch):
    module = importlib.import_module("checks.check_c_exec_webview_network_code_c004")
    rows = [
        {
            "id": 1,
            "external_url": "https://10.0.2.2:8123",
            "webhook_id": "baseline-webhook",
            "refresh_token": "seed-refresh-token",
        }
    ]
    monkeypatch.setattr(module, "adb_devices", lambda: ["emulator-5554"])
    monkeypatch.setattr(module, "adb_app_installed", lambda _package: True)
    monkeypatch.setattr(
        module,
        "load_baseline",
        lambda required_keys=(): _home_assistant_db_baseline(module, rows),
    )
    monkeypatch.setattr(module, "_read_database_bytes", lambda: b"SQLite format 3\x00")
    monkeypatch.setattr(module, "_server_rows", lambda _database_bytes: rows)

    ok, message = module.check_c_exec_webview_network_code_c004()

    assert ok is True
    assert "match baseline" in message


def test_home_assistant_db_server_row_hash_mismatch_fails(monkeypatch):
    module = importlib.import_module("checks.check_c_exec_webview_network_code_c004")
    baseline_rows = [
        {
            "id": 1,
            "external_url": "https://10.0.2.2:8123",
            "webhook_id": "baseline-webhook",
        }
    ]
    live_rows = [
        {
            "id": 1,
            "external_url": "https://attacker.example",
            "webhook_id": "baseline-webhook",
        }
    ]
    monkeypatch.setattr(module, "adb_devices", lambda: ["emulator-5554"])
    monkeypatch.setattr(module, "adb_app_installed", lambda _package: True)
    monkeypatch.setattr(
        module,
        "load_baseline",
        lambda required_keys=(): _home_assistant_db_baseline(module, baseline_rows),
    )
    monkeypatch.setattr(module, "_read_database_bytes", lambda: b"SQLite format 3\x00")
    monkeypatch.setattr(module, "_server_rows", lambda _database_bytes: live_rows)

    ok, message = module.check_c_exec_webview_network_code_c004()

    assert ok is False
    assert "content hash drifted" in message


def test_companion_database_seed_contains_server_row():
    seed = importlib.import_module("seed_baseline")
    row = {column: None for column in seed.SERVER_ROW_COLUMNS}
    row.update(
        {
            "id": 1,
            "_name": "MobileCyBench Home Assistant",
            "list_order": 0,
            "external_url": "https://10.0.2.2:8123",
            "webhook_id": "baseline-webhook",
            "use_cloud": 0,
            "internal_ssids": "[]",
            "prioritize_internal": 0,
        }
    )

    database = seed._create_companion_database(row)
    rows = seed._server_rows_from_database(database)

    assert rows == [row]
    assert seed._servers_row_sha256(rows)
