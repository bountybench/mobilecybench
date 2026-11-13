"""attacker_adb=False: remote_attacker ablation with no device access in the
agent phase or the exploit.sh replay."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import docker
import pytest

from agent.prompts.prompts import build_remote_attacker_prompt
from models.config import RunnerConfig
from utils import setup_utils
from workflows.base import Workflow


def _config(**overrides) -> RunnerConfig:
    base = dict(
        build_type="skip-apk",
        model="test",
        agent_image="test:latest",
        max_iterations=10,
        max_model_response_tokens=1000,
        dry_run=False,
        emulator_backend="native",
        emulator_display="headed",
        network_mode="restricted",
        workflow="redteam",
        probe_only=True,
        attacker_model="remote_attacker",
    )
    base.update(overrides)
    return RunnerConfig(**base)


# ---- config ---------------------------------------------------------------


def test_attacker_adb_defaults_true():
    assert _config().attacker_adb is True


def test_attacker_adb_false_accepted_for_remote_attacker():
    assert _config(attacker_adb=False).attacker_adb is False


def test_attacker_adb_false_rejected_for_malicious_app():
    with pytest.raises(ValueError, match="attacker_adb=False"):
        _config(attacker_model="malicious_app", attacker_adb=False)


# ---- prompt ---------------------------------------------------------------


@pytest.mark.parametrize("no_codebase", [False, True])
def test_no_adb_prompt_drops_device_access(no_codebase):
    kwargs = dict(
        package_name="com.example",
        app_server="server:8080",
        username="attacker",
        password="pw",
        no_codebase=no_codebase,
        agent_mode="external",
    )
    default = build_remote_attacker_prompt(**kwargs)
    no_adb = build_remote_attacker_prompt(**kwargs, attacker_adb=False)

    assert "**ADB**" in default
    assert "**ADB**" not in no_adb
    assert "via ADB" not in no_adb
    assert "with ADB access" not in no_adb
    assert "running app" not in no_adb
    assert "No device access" in no_adb
    assert "attacker" in no_adb and "server:8080" in no_adb
    assert ("/app/apk/" in no_adb) == no_codebase


def test_default_prompt_unchanged_by_new_parameter():
    kwargs = dict(package_name="com.example", agent_mode="external")
    assert build_remote_attacker_prompt(**kwargs) == build_remote_attacker_prompt(
        **kwargs, attacker_adb=True
    )


# ---- replay ---------------------------------------------------------------


class _ConcreteWorkflow(Workflow):
    def validate_arguments(self):
        pass

    def setup_runtime_environment(self):
        pass

    def evaluate(self):
        return {}

    def _build_apks_from_source(self):
        pass


@pytest.mark.parametrize("no_adb", [False, True])
def test_run_exploit_passes_no_adb_flag(tmp_path: Path, no_adb: bool):
    wf = _ConcreteWorkflow(_config(attacker_adb=not no_adb), "testapp", tmp_path)
    exploit_dir = tmp_path / "agent_exploit"
    exploit_dir.mkdir()
    (exploit_dir / "exploit.sh").write_text("true")
    runner = tmp_path / "runner.sh"
    runner.write_text('#!/bin/bash\necho "ARGS: $*"\n')

    wf._run_exploit(
        exploit_dir=exploit_dir,
        output_dir=tmp_path / "out",
        exploit_runner=runner,
        exploit_image="test:latest",
        codebase_dir=tmp_path,
        replay_apk=None,
        no_adb=no_adb,
    )

    stdout = (tmp_path / "out" / "stdout.txt").read_text()
    assert ("--no-adb" in stdout) == no_adb


# ---- agent container ------------------------------------------------------


@pytest.mark.parametrize("attacker_adb", [True, False])
@patch("agent.runtime.container.docker.from_env")
def test_agent_environment_adb_proxy_follows_flag(
    mock_from_env, tmp_path: Path, attacker_adb: bool
):
    from agent.runtime.container import setup_agent_environment

    mock_client = MagicMock()
    mock_from_env.return_value = mock_client
    mock_client.images.get.return_value = MagicMock()
    mock_container = MagicMock()
    mock_container.exec_run.return_value = MagicMock(exit_code=0, output=b"")
    mock_client.containers.run.return_value = mock_container
    mock_client.containers.get.side_effect = docker.errors.NotFound("not found")

    app_dir = tmp_path / "app"
    (app_dir / "codebase" / ".git").mkdir(parents=True)

    with patch(
        "agent.runtime.container.AgentEnvironment._setup_agent_codebase",
        return_value={},
    ), patch("agent.runtime.container._start_adb_proxy") as start_proxy, patch(
        "agent.runtime.container._stop_adb_proxy"
    ), patch(
        "agent.runtime.container._disable_emulator_root"
    ), patch(
        "agent.runtime.container.firewall.start"
    ), patch(
        "agent.runtime.container.firewall.proxy_url", return_value="http://proxy"
    ), patch(
        "agent.runtime.container.firewall.build_no_proxy", return_value=""
    ):
        setup_agent_environment(
            app_dir=app_dir,
            agent_image="test:latest",
            metadata={"package_name": "com.example", "commit_version": "HEAD"},
            network_mode="restricted",
            workflow="redteam",
            attacker_adb=attacker_adb,
        )

    env_vars = mock_client.containers.run.call_args.kwargs["environment"]
    assert start_proxy.called == attacker_adb
    assert ("ADB_SERVER_SOCKET" in env_vars) == attacker_adb
    assert ("ANDROID_ADB_SERVER_PORT" in env_vars) == attacker_adb


# ---- connectivity check ---------------------------------------------------


def _container_with_adb_output(stdout: bytes) -> MagicMock:
    container = MagicMock()
    container.exec_run.return_value = MagicMock(exit_code=0, output=(stdout, b""))
    return container


@patch("utils.setup_utils.subprocess.run")
def test_connectivity_no_adb_passes_when_agent_cannot_see_emulator(mock_run):
    mock_run.return_value = MagicMock(stdout="emulator-5554\tdevice\n")
    container = _container_with_adb_output(b"List of devices attached\n")
    setup_utils.check_connectivity(container, None, expect_agent_adb=False)


@patch("utils.setup_utils.subprocess.run")
def test_connectivity_no_adb_fails_when_agent_sees_emulator(mock_run):
    mock_run.return_value = MagicMock(stdout="emulator-5554\tdevice\n")
    container = _container_with_adb_output(b"emulator-5554\tdevice\n")
    with pytest.raises(RuntimeError, match="adb blocked"):
        setup_utils.check_connectivity(container, None, expect_agent_adb=False)
