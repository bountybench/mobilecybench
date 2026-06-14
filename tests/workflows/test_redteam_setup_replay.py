"""Tests for replay-mode gating in RedTeamWorkflow.setup_runtime_environment.

Bug context: prior to this gating, setup_runtime_environment unconditionally
invoked setup_agent_environment(agent_image=...), which pulled the agent
Docker image even when replay_exploit_dir was set and the agent loop would
never run. On hosts without the configured tag cached locally and with the
tag absent from the registry, this aborted the replay before the emulator
booted.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from models.config import RunnerConfig
from workflows.redteam import MaliciousAppOps, RedTeamWorkflow

_BASE_CONFIG = {
    "workflow": "redteam",
    "probe_only": True,
    "attacker_model": "malicious_app",
    "task": None,
    "synthetic_vuln_id": None,
    "build_type": "skip-apk",
    "model": "test",
    "agent_image": "cybench/mobilecybench:does-not-exist",
    "max_iterations": 10,
    "max_model_response_tokens": 1000,
    "dry_run": False,
    "emulator_backend": "native",
    "emulator_display": "headless",
    "network_mode": "permissive",
}


def _make_workflow(tmp_path: Path, replay_dir: Path | None) -> RedTeamWorkflow:
    cfg = {**_BASE_CONFIG}
    if replay_dir is not None:
        cfg["replay_exploit_dir"] = str(replay_dir)
    config = RunnerConfig(**cfg)
    workflow = RedTeamWorkflow.__new__(RedTeamWorkflow)
    workflow.config = config
    workflow.app_name = "moememos"
    workflow.app_dir = tmp_path / "apps" / "moememos"
    workflow.app_dir.mkdir(parents=True, exist_ok=True)
    workflow.project_root = tmp_path
    workflow.metadata = {"sdk": "35", "app_server": "memos-server"}
    workflow.agent_env = None
    workflow._ops = MaliciousAppOps()
    workflow._bundle = MagicMock()
    workflow.setup_apks = MagicMock()
    workflow._preflight_cleanup_app_runtime = MagicMock()
    workflow._mark_app_backend_active = MagicMock()
    workflow._runtime_apk = MagicMock(return_value=tmp_path / "victim.apk")
    (tmp_path / "victim.apk").write_bytes(b"")
    workflow._prepare_runtime_codebase = MagicMock()
    workflow._run_agent_login = MagicMock()
    workflow._inject_apk_template = MagicMock()
    return workflow


def _patch_runtime_deps():
    return [
        patch("utils.setup_utils.check_connectivity"),
        patch("utils.setup_utils.install_app_and_setup_backend"),
        patch("utils.emulator_certs.inject_system_ca"),
        patch("utils.emulator_manager.EmulatorManager"),
        patch("agent.runtime.container.setup_agent_environment"),
    ]


def test_replay_exploit_dir_skips_agent_container_setup(tmp_path):
    """When replay_exploit_dir is set, agent container init must be skipped."""
    replay_dir = tmp_path / "agent_exploit"
    (replay_dir / "exploit_apk").mkdir(parents=True)
    workflow = _make_workflow(tmp_path, replay_dir=replay_dir)

    patches = _patch_runtime_deps()
    started = [p.start() for p in patches]
    try:
        (
            check_conn,
            install_app,
            inject_ca,
            EmulatorManager,
            setup_agent_env,
        ) = started
        EmulatorManager.return_value = MagicMock()

        workflow.setup_runtime_environment()

        # The whole point: agent docker image is never touched in replay mode.
        setup_agent_env.assert_not_called()
        check_conn.assert_not_called()
        workflow._run_agent_login.assert_not_called()
        assert workflow.agent_env is None
    finally:
        for p in patches:
            p.stop()


def test_non_replay_path_still_calls_agent_setup(tmp_path):
    """Sanity check: non-replay runs still invoke the agent container setup."""
    workflow = _make_workflow(tmp_path, replay_dir=None)

    patches = _patch_runtime_deps()
    started = [p.start() for p in patches]
    try:
        (
            check_conn,
            install_app,
            inject_ca,
            EmulatorManager,
            setup_agent_env,
        ) = started
        EmulatorManager.return_value = MagicMock()
        agent_env = MagicMock()
        setup_agent_env.return_value = agent_env

        workflow.setup_runtime_environment()

        setup_agent_env.assert_called_once()
        assert workflow.agent_env is agent_env
        workflow._run_agent_login.assert_called_once()
    finally:
        for p in patches:
            p.stop()
