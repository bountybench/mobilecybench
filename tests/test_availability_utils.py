import json
import subprocess

from utils.availability_utils import check_container_health


def _docker_inspect_result(state):
    return subprocess.CompletedProcess(
        args=["docker", "inspect", "container"],
        returncode=0,
        stdout=json.dumps([{"State": state}]),
        stderr="",
    )


def test_container_with_healthy_healthcheck_passes(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: _docker_inspect_result(
            {"Health": {"Status": "healthy"}, "Running": True}
        ),
    )

    assert check_container_health("container")


def test_running_container_without_healthcheck_passes(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: _docker_inspect_result({"Running": True}),
    )

    assert check_container_health("container")


def test_stopped_container_without_healthcheck_fails(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: _docker_inspect_result(
            {"Running": False, "Status": "exited"}
        ),
    )

    assert not check_container_health("container")


def test_missing_container_fails(monkeypatch):
    def fail_inspect(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["docker", "inspect", "container"])

    monkeypatch.setattr(subprocess, "run", fail_inspect)

    assert not check_container_health("container")
