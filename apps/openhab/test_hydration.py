import importlib.util
import subprocess
from pathlib import Path

import pytest


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
    login_idx = events.index(("run", "prepare_victim.sh", "1"))
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
