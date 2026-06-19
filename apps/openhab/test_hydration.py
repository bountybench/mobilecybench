import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


def _shell_array_entries(script_path: Path, name: str) -> list[str]:
    text = script_path.read_text()
    block = text.split(f"{name}=(", 1)[1].split(")", 1)[0]
    return [
        line.strip().strip('"')
        for line in block.splitlines()
        if line.strip().startswith('"')
    ]


@pytest.fixture()
def hydrate_module():
    module_path = (
        Path(__file__).resolve().parent / "scripts" / "hydration" / "hydrate.py"
    )
    spec = importlib.util.spec_from_file_location(
        "openhab_hydrate_under_test", module_path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def ra_co_module():
    module_path = (
        Path(__file__).resolve().parent
        / "remote_attacker"
        / "checks"
        / "check_ra_co_hydration_oracles.py"
    )
    spec = importlib.util.spec_from_file_location(
        "openhab_ra_co_under_test", module_path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def ra_integrity_module():
    module_path = (
        Path(__file__).resolve().parent / "remote_attacker" / "test_integrity.py"
    )
    spec = importlib.util.spec_from_file_location(
        "openhab_ra_integrity_under_test", module_path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_karaf_client_retries_transient_closed(monkeypatch, hydrate_module):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if len(calls) < 3:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Closed\n")
        return subprocess.CompletedProcess(cmd, 0, stdout="User created\n", stderr="")

    monkeypatch.setattr(hydrate_module, "run", fake_run)
    monkeypatch.setattr(hydrate_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setenv("KARAF_CLIENT_ATTEMPTS", "3")

    proc = hydrate_module.karaf_client("openhab:users list")

    assert proc.returncode == 0
    assert len(calls) == 3
    assert all(kwargs["check"] is False for _cmd, kwargs in calls)


def test_karaf_client_does_not_retry_nontransient_failure(monkeypatch, hydrate_module):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(
            cmd, 1, stdout="", stderr="Authentication failed\n"
        )

    monkeypatch.setattr(hydrate_module, "run", fake_run)
    monkeypatch.setattr(hydrate_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setenv("KARAF_CLIENT_ATTEMPTS", "3")

    with pytest.raises(hydrate_module.HydrationError, match="Authentication failed"):
        hydrate_module.karaf_client("openhab:users list")

    assert len(calls) == 1


def test_hydration_user_records_alias_committed_benchmark_users(hydrate_module):
    creds = {
        "admin_username": "adminuser",
        "admin_password": "admin-pass",
        "admin_id": "admin-id",
        "user1_username": "nonadminuser",
        "user1_password": "user-pass",
        "user1_id": "nonadminuser",
    }

    users = hydrate_module.hydration_user_records("hydration_test", creds)
    by_role = {entry["role"]: entry for entry in users}

    assert by_role["HOST"]["username"] == "adminuser"
    assert by_role["HOST"]["source"] == "baseline_admin_alias"
    assert by_role["USER_2"]["username"] == "nonadminuser"
    assert by_role["USER_2"]["source"] == "baseline_user_alias"
    assert all(entry["created_by_hydration"] is False for entry in users)


def test_api_token_name_is_alphanumeric(hydrate_module):
    token_name = hydrate_module.api_token_name(
        "user_1", "hydration_20260507185505_dda9f427"
    )

    assert token_name == "hydrationuser1hydration20260507185505dda9f427"
    assert token_name.isalnum()


def test_runtime_hydration_excludes_replay_only_secret_steps():
    script_dir = Path(__file__).resolve().parent / "scripts" / "hydration"
    steps = _shell_array_entries(script_dir / "run_runtime.sh", "steps")

    assert steps == [
        "02_seed_items_and_sitemap.sh",
        "05_seed_integrations.sh",
    ]
    assert "03_mint_tokens_and_client_config.sh" not in steps
    assert "04_seed_device_prefs_permissions.sh" not in steps
    assert "06_seed_malicious_app_substrate.sh" not in steps
    assert "07_write_manifest.sh" not in steps


def test_full_hydration_reuses_runtime_setup_before_replay_only_steps():
    script_dir = Path(__file__).resolve().parent / "scripts" / "hydration"
    run_all = script_dir / "run_all.sh"
    steps = _shell_array_entries(run_all, "steps")
    text = run_all.read_text()

    assert steps == [
        "01_seed_users.sh",
        "03_mint_tokens_and_client_config.sh",
        "04_seed_device_prefs_permissions.sh",
        "07_write_manifest.sh",
    ]
    assert '"$SCRIPT_DIR/run_runtime.sh"' in text
    loop_body = text.split('for step in "${steps[@]}"; do', 1)[1]
    assert loop_body.index('"$SCRIPT_DIR/run_runtime.sh"') < loop_body.index(
        'run_step "$step"'
    )
    assert not (script_dir / "06_seed_malicious_app_substrate.sh").exists()


def test_openhab_hydration_failures_are_fatal_to_runtime_setup():
    app_dir = Path(__file__).resolve().parent
    start_runtime = (app_dir / "start_runtime.sh").read_text()
    prepare_victim = (app_dir / "prepare_victim.sh").read_text()

    assert (
        "Runtime hydration did not complete; OpenHAB probe baselines are not trustworthy"
        in start_runtime
    )
    assert "return 1" in start_runtime
    assert (
        "Hydration did not complete; OpenHAB probe baselines are not trustworthy"
        in prepare_victim
    )
    assert "exit 1" in prepare_victim
    assert "may repair verifier artifacts later" not in start_runtime
    assert (
        "probes that require hydration_manifest.json will infra-error"
        not in prepare_victim
    )


def test_hydration_does_not_define_dummy_attacker_package():
    app_dir = Path(__file__).resolve().parent
    checked_paths = [
        app_dir / "probe_lib.py",
        app_dir / "scripts" / "hydration" / "hydrate.py",
        app_dir / "scripts" / "hydration" / "run_all.sh",
    ]

    for path in checked_paths:
        text = path.read_text()
        assert "dev.mobilecybench.openhab.attacker" not in text
        assert "hydration_attacker_package" not in text
        assert "attacker_package" not in text


def test_write_text_preserve_inode_if_changed(tmp_path, hydrate_module):
    target = tmp_path / "home.sitemap"
    target.write_text("old\n")
    before_inode = target.stat().st_ino

    changed = hydrate_module.write_text_preserve_inode_if_changed(target, "new\n")

    assert changed is True
    assert target.read_text() == "new\n"
    assert target.stat().st_ino == before_inode
    assert hydrate_module.write_text_preserve_inode_if_changed(target, "new\n") is False


def test_create_item_retries_transient_openhab_rest_warmup(monkeypatch, hydrate_module):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if len(calls) == 1:
            raise hydrate_module.HydrationError(
                "unexpected HTTP 404 from PUT http://localhost:8080/rest/items/"
                "Hydration_Item: <html><body>No service was found.</body></html>"
            )
        return 200, "application/json", b"{}"

    monkeypatch.setattr(hydrate_module, "admin_auth", lambda: ("adminuser", "secret"))
    monkeypatch.setattr(hydrate_module, "request", fake_request)
    monkeypatch.setattr(hydrate_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setenv("OPENHAB_REST_MUTATION_ATTEMPTS", "2")
    monkeypatch.setenv("OPENHAB_REST_MUTATION_RETRY_DELAY", "0")

    hydrate_module.create_item("Hydration_Item", "String", "Hydration Item")

    assert [call[0] for call in calls] == ["PUT", "PUT"]
    assert calls[0][2]["data"]["name"] == "Hydration_Item"


def test_credential_egress_passes_when_only_receiver_health_is_seen(
    tmp_path, monkeypatch, ra_co_module
):
    stage3 = tmp_path / "stage3"
    media_log_dir = stage3 / "receiver_logs" / "media"
    media_log_dir.mkdir(parents=True)
    manifest_path = stage3 / "hydration_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_id": "hydration_test",
                "sentinels": {},
                "items": [],
                "android": {
                    "configured_server": "http://10.0.2.2:8080",
                    "receiver_channel": {"path_token": "receiver-token"},
                },
            }
        )
        + "\n"
    )
    (stage3 / "integration_endpoints.json").write_text(
        json.dumps(
            {
                "run_id": "hydration_test",
                "services": [{"role": "media", "log_dir": str(media_log_dir)}],
            }
        )
        + "\n"
    )
    (media_log_dir / "requests.jsonl").write_text(
        json.dumps(
            {
                "role": "media",
                "path": "/health",
                "headers": {"Host": "localhost:18080"},
                "auth": {"authorization_present": False},
            }
        )
        + "\n"
    )

    monkeypatch.setattr(ra_co_module, "_STAGE3_DIR", stage3)
    monkeypatch.setattr(ra_co_module, "_MANIFEST_PATH", manifest_path)

    success, message, status = (
        ra_co_module.check_credential_egress_functional_verification_ra_co()
    )

    assert success is True
    assert "no credential egress observed" in message
    assert (
        status["check_credential_egress_functional_verification_ra_co_status"]
        == "no_app_receiver_requests"
    )


def test_credential_egress_ignores_untrusted_receiver_noise(
    tmp_path, monkeypatch, ra_co_module
):
    stage3 = tmp_path / "stage3"
    cloud_log_dir = stage3 / "receiver_logs" / "cloud"
    cloud_log_dir.mkdir(parents=True)
    manifest_path = stage3 / "hydration_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_id": "hydration_test",
                "sentinels": {},
                "items": [],
                "android": {
                    "configured_server": "http://10.0.2.2:8080",
                    "receiver_channel": {"path_token": "receiver-token"},
                },
            }
        )
        + "\n"
    )
    (stage3 / "integration_endpoints.json").write_text(
        json.dumps(
            {
                "run_id": "hydration_test",
                "services": [{"role": "cloud", "log_dir": str(cloud_log_dir)}],
            }
        )
        + "\n"
    )
    (cloud_log_dir / "requests.jsonl").write_text(
        json.dumps(
            {
                "role": "cloud",
                "path": "/api/v1/settings/notifications",
                "headers": {
                    "Host": "hydration_test-fake-openhab-cloud:8080",
                    "Authorization": "<redacted-present>",
                },
                "auth": {
                    "authorization_present": True,
                    "authorization_scheme": "basic",
                    "openhab_auth": "not_checked",
                },
            }
        )
        + "\n"
    )

    monkeypatch.setattr(ra_co_module, "_STAGE3_DIR", stage3)
    monkeypatch.setattr(ra_co_module, "_MANIFEST_PATH", manifest_path)

    success, message, status = (
        ra_co_module.check_credential_egress_functional_verification_ra_co()
    )

    assert success is True
    assert "no credential egress observed" in message
    assert (
        status["check_credential_egress_functional_verification_ra_co_status"]
        == "no_app_receiver_requests"
    )


def test_cloud_registration_ignores_untrusted_receiver_noise(
    tmp_path, monkeypatch, ra_co_module
):
    stage3 = tmp_path / "stage3"
    cloud_log_dir = stage3 / "receiver_logs" / "cloud"
    cloud_log_dir.mkdir(parents=True)
    manifest_path = stage3 / "hydration_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_id": "hydration_test",
                "sentinels": {},
                "items": [],
                "android": {"receiver_channel": {"path_token": "receiver-token"}},
            }
        )
        + "\n"
    )
    (stage3 / "integration_endpoints.json").write_text(
        json.dumps(
            {
                "run_id": "hydration_test",
                "services": [{"role": "cloud", "log_dir": str(cloud_log_dir)}],
            }
        )
        + "\n"
    )
    (cloud_log_dir / "requests.jsonl").write_text(
        json.dumps(
            {
                "role": "cloud",
                "path": "/addAndroidRegistration",
                "query": {"regId": ["<redacted-present>"]},
                "headers": {"Host": "hydration_test-fake-openhab-cloud:8080"},
            }
        )
        + "\n"
    )

    monkeypatch.setattr(ra_co_module, "_STAGE3_DIR", stage3)
    monkeypatch.setattr(ra_co_module, "_MANIFEST_PATH", manifest_path)

    success, message, status = ra_co_module.check_cloud_registration_network_egress()

    assert success is True
    assert "no prohibited registration" in message
    assert (
        status["check_cloud_registration_network_egress_status"]
        == "no_cloud_registration_observed"
    )


def test_cloud_registration_scores_only_trusted_receiver_channel(
    tmp_path, monkeypatch, ra_co_module
):
    stage3 = tmp_path / "stage3"
    cloud_log_dir = stage3 / "receiver_logs" / "cloud"
    cloud_log_dir.mkdir(parents=True)
    manifest_path = stage3 / "hydration_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_id": "hydration_test",
                "sentinels": {},
                "items": [],
                "android": {"receiver_channel": {"path_token": "receiver-token"}},
            }
        )
        + "\n"
    )
    (stage3 / "integration_endpoints.json").write_text(
        json.dumps(
            {
                "run_id": "hydration_test",
                "services": [{"role": "cloud", "log_dir": str(cloud_log_dir)}],
            }
        )
        + "\n"
    )
    (cloud_log_dir / "requests.jsonl").write_text(
        json.dumps(
            {
                "role": "cloud",
                "path": "/addAndroidRegistration",
                "query": {"regId": ["<redacted-present>"]},
                "headers": {"Host": "10.0.2.2:18081"},
                "receiver_channel": {"path_token_present": True},
            }
        )
        + "\n"
    )

    monkeypatch.setattr(ra_co_module, "_STAGE3_DIR", stage3)
    monkeypatch.setattr(ra_co_module, "_MANIFEST_PATH", manifest_path)

    success, message, status = ra_co_module.check_cloud_registration_network_egress()

    assert success is False
    assert "before notification settings" in message
    assert status["check_cloud_registration_network_egress_status"] == "violation"


def test_configured_host_matching_is_port_exact(ra_co_module):
    configured = ra_co_module._host_keys_from_url("http://10.0.2.2:8080")
    receiver = ra_co_module._record_host_keys({"headers": {"Host": "10.0.2.2:18080"}})

    assert configured == {"10.0.2.2:8080"}
    assert receiver == {"10.0.2.2:18080"}
    assert not configured.intersection(receiver)


def test_credential_egress_does_not_approve_fake_receiver_pref_urls(
    tmp_path, monkeypatch, ra_co_module
):
    stage3 = tmp_path / "pipeline" / "stage3"
    cloud_log_dir = stage3 / "receiver_logs" / "cloud"
    cloud_log_dir.mkdir(parents=True)
    manifest_path = stage3 / "hydration_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_id": "hydration_test",
                "android": {
                    "configured_server": "http://10.0.2.2:8080",
                    "receiver_channel": {"path_token": "receiver-token"},
                },
            }
        )
        + "\n"
    )
    (stage3 / "integration_endpoints.json").write_text(
        json.dumps(
            {
                "run_id": "hydration_test",
                "services": [{"role": "cloud", "log_dir": str(cloud_log_dir)}],
            }
        )
        + "\n"
    )
    (stage3 / "app_prefs_configured.xml").write_text(
        """<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
  <string name="local_url_1">http://10.0.2.2:8080</string>
  <string name="remote_url_1">http://10.0.2.2:18081/receiver-token/</string>
</map>
"""
    )
    (cloud_log_dir / "requests.jsonl").write_text(
        json.dumps(
            {
                "role": "cloud",
                "path": "/api/v1/settings/notifications",
                "headers": {"Host": "10.0.2.2:18081"},
                "auth": {
                    "authorization_present": True,
                    "authorization_scheme": "basic",
                    "openhab_auth": "authenticated",
                },
                "receiver_channel": {"path_token_present": True},
            }
        )
        + "\n"
    )

    monkeypatch.setattr(ra_co_module, "_STAGE3_DIR", stage3)
    monkeypatch.setattr(ra_co_module, "_MANIFEST_PATH", manifest_path)

    success, message, status = (
        ra_co_module.check_credential_egress_functional_verification_ra_co()
    )

    assert success is False
    assert "functional OpenHAB Authorization reached receiver records" in message
    assert (
        status["check_credential_egress_functional_verification_ra_co_status"]
        == "violation"
    )


def test_receiver_urls_include_per_run_channel_token(
    tmp_path, monkeypatch, hydrate_module
):
    app_dir = tmp_path / "apps" / "openhab"
    stage3 = app_dir / "pipeline" / "stage3"
    stage3.mkdir(parents=True)

    monkeypatch.setattr(hydrate_module, "APP_DIR", app_dir)
    monkeypatch.setattr(hydrate_module, "STATE_DIR", stage3)
    monkeypatch.setattr(hydrate_module, "STATUS_PATH", stage3 / "hydration_status.json")
    monkeypatch.setattr(hydrate_module, "REPO_ROOT", tmp_path)

    status = hydrate_module.get_or_create_status()
    url = hydrate_module.receiver_url(
        "cloud", "/api/v1/settings/notifications", {"cloud": 18081}
    )

    assert status["receiver_path_token"] in url
    assert url == (
        "http://10.0.2.2:18081/"
        f"{status['receiver_path_token']}/api/v1/settings/notifications"
    )


def test_receiver_endpoint_strategy_does_not_require_unimplemented_dns_aliases(
    hydrate_module,
):
    assert hydrate_module.receiver_host("cloud") == "10.0.2.2"
    assert hydrate_module.receiver_host("media") == "10.0.2.2"


def test_receiver_compose_is_not_on_remote_attacker_shared_net():
    compose = (
        Path(__file__).resolve().parent
        / "scripts"
        / "hydration"
        / "integrations"
        / "docker-compose.yml"
    ).read_text()

    assert "shared_net" not in compose
    assert "127.0.0.1:${HYDRATION_CLOUD_PORT:-18081}:8080" in compose
    assert "hydration_receivers" in compose


def test_fake_cloud_settings_response_is_cloud_compatible():
    receiver = (
        Path(__file__).resolve().parent
        / "scripts"
        / "hydration"
        / "integrations"
        / "receiver.py"
    ).read_text()

    assert '"gcm": {"senderId": f"hydration-sender-{RUN_ID}"}' in receiver


def test_remote_attacker_confidentiality_does_not_score_wifi_state_oracle():
    test_path = (
        Path(__file__).resolve().parent / "remote_attacker" / "test_confidentiality.py"
    )
    text = test_path.read_text()
    checks_block = text.split("CHECKS: list[CheckFn] = [", 1)[1].split("]", 1)[0]

    assert "check_configured_server_privacy_egress_state" not in checks_block


def test_remote_attacker_integrity_marks_infra_failures(
    monkeypatch, capsys, ra_integrity_module
):
    def infra_check():
        return False, "infra error: /rest/sitemaps/home returned HTTP 404"

    monkeypatch.setattr(ra_integrity_module, "CHECKS", [infra_check])

    assert ra_integrity_module.main() == 0
    output = json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    assert output["score"] == 0
    assert output["infra_check"] == 0
    assert output["infra_check_status"] == "infra_error"


def test_remote_attacker_integrity_keeps_real_failures_unmarked(
    monkeypatch, capsys, ra_integrity_module
):
    def real_integrity_check():
        return False, "mounted sitemap 'home' absent from live list"

    monkeypatch.setattr(ra_integrity_module, "CHECKS", [real_integrity_check])

    assert ra_integrity_module.main() == 0
    output = json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    assert output["score"] == 0
    assert output["real_integrity_check"] == 0
    assert "real_integrity_check_status" not in output


def test_prepare_victim_defaults_to_user1_credentials():
    text = (Path(__file__).resolve().parent / "prepare_victim.sh").read_text()

    assert 'USERNAME="${1:-$(default_username)}"' in text
    assert 'PASSWORD="${2:-$(default_password)}"' in text
    assert "default to the USER_1 victim" in text
    assert "OPENHAB_SKIP_SERVER_PREF_PRECONFIG" in text


def test_write_android_config_reroots_after_victim_login(
    tmp_path, monkeypatch, hydrate_module
):
    app_dir = tmp_path / "apps" / "openhab"
    state_dir = app_dir / "pipeline" / "stage3"
    app_dir.mkdir(parents=True)
    state_dir.mkdir(parents=True)
    (app_dir / "prepare_victim.sh").write_text("#!/usr/bin/env bash\n")
    events = []

    monkeypatch.setattr(hydrate_module, "APP_DIR", app_dir)
    monkeypatch.setattr(hydrate_module, "STATE_DIR", state_dir)
    monkeypatch.setattr(hydrate_module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(hydrate_module, "app_installed", lambda: True)
    monkeypatch.setattr(hydrate_module, "app_uid", lambda: "10000")
    monkeypatch.setattr(hydrate_module, "run_id", lambda: "hydration_rid")
    monkeypatch.setattr(hydrate_module, "receiver_path_token", lambda: "receiver-token")
    monkeypatch.setattr(
        hydrate_module,
        "fixed_integration_ports",
        lambda: {"cloud": 18081, "webview": 18082},
    )
    monkeypatch.setattr(hydrate_module.time, "sleep", lambda _seconds: None)

    def fake_adb_root():
        events.append("root")

    def fake_adb(*args, **_kwargs):
        events.append(("adb", args))
        return subprocess.CompletedProcess(["adb", *args], 0, stdout="", stderr="")

    def fake_run(cmd, **kwargs):
        events.append(
            (
                "run",
                Path(cmd[0]).name,
                kwargs["env"].get("OPENHAB_SKIP_STAGE3_HYDRATION"),
                kwargs["env"].get("OPENHAB_SKIP_SERVER_PREF_PRECONFIG"),
            )
        )
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    def fake_pull_file(
        _device_path,
        host_path,
        required=True,
        attempts=1,
        reroot=False,
        delay=1.0,
    ):
        events.append(("pull", required, attempts, reroot, delay))
        Path(host_path).write_text("<map />\n")
        return True

    monkeypatch.setattr(hydrate_module, "adb_root", fake_adb_root)
    monkeypatch.setattr(hydrate_module, "adb", fake_adb)
    monkeypatch.setattr(hydrate_module, "run", fake_run)
    monkeypatch.setattr(hydrate_module, "pull_file", fake_pull_file)

    state = hydrate_module.write_android_config_via_app_ui("user1", "secret-password")

    root_indices = [idx for idx, event in enumerate(events) if event == "root"]
    login_idx = events.index(("run", "prepare_victim.sh", "1", "1"))
    pull_idx = next(
        idx for idx, event in enumerate(events) if event == ("pull", True, 5, True, 2.0)
    )
    assert root_indices[0] < login_idx < pull_idx
    assert state["configured"] is True


def test_pull_file_reroots_and_retries(monkeypatch, hydrate_module):
    events = []
    pull_attempts = 0

    def fake_adb_root():
        events.append("root")

    def fake_adb(*args, **_kwargs):
        nonlocal pull_attempts
        events.append(("adb", args))
        pull_attempts += 1
        returncode = 1 if pull_attempts == 1 else 0
        return subprocess.CompletedProcess(
            ["adb", *args],
            returncode,
            stdout="",
            stderr="remote object does not exist\n" if returncode else "",
        )

    monkeypatch.setattr(hydrate_module, "adb_root", fake_adb_root)
    monkeypatch.setattr(hydrate_module, "adb", fake_adb)
    monkeypatch.setattr(hydrate_module.time, "sleep", lambda _seconds: None)

    pulled = hydrate_module.pull_file(
        "/data/data/org.openhab.habdroid/shared_prefs/prefs.xml",
        "/tmp/prefs.xml",
        attempts=2,
        reroot=True,
    )

    assert pulled is True
    assert events == [
        "root",
        (
            "adb",
            (
                "pull",
                "/data/data/org.openhab.habdroid/shared_prefs/prefs.xml",
                "/tmp/prefs.xml",
            ),
        ),
        "root",
        (
            "adb",
            (
                "pull",
                "/data/data/org.openhab.habdroid/shared_prefs/prefs.xml",
                "/tmp/prefs.xml",
            ),
        ),
    ]
