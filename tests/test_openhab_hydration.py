import importlib.util
import subprocess
from pathlib import Path

import pytest


@pytest.fixture()
def hydrate_module():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "apps"
        / "openhab"
        / "scripts"
        / "hydration"
        / "hydrate.py"
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
