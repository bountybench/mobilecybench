"""Tests for Workflow base class and implementations."""

import subprocess
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from models.config import RunnerConfig
from workflows.redteam import RedTeamWorkflow


def _config(**overrides) -> RunnerConfig:
    """Create a RunnerConfig with sensible test defaults."""

    defaults = {
        "build_type": "source",
        "model": "gpt-4",
        "agent_image": "test-image:latest",
        "max_iterations": 10,
        "max_model_response_tokens": 1000,
        "dry_run": False,
        "emulator_display": "headed",
        "emulator_backend": "native",
        "network_mode": "restricted",
        "script_timeout": 600,
        "workflow": "redteam",
        "probe_only": True,
        "attacker_model": "remote_attacker",
        "task": None,
        "synthetic_vuln_id": None,
    }
    return RunnerConfig(**{**defaults, **overrides})


def _patch_agent_container(*, create_network=None):
    fake_module = types.ModuleType("agent.runtime.container")
    fake_module.SHARED_NET = "shared_net"
    fake_module.AGENT_NET = "agent_net"
    fake_module.create_docker_network = create_network or (lambda name, **kwargs: None)
    return patch.dict("sys.modules", {"agent.runtime.container": fake_module})


class TestRunAgentLogging:
    """Workflow.run_agent emits one terminal log line per run with neutral
    phrasing (`Agent run finished: status=...`). Two callsites exist (BYO +
    custom branches in workflows/base.py); the runner-side duplicate was
    removed. These tests guard against the old phrasings creeping back."""

    @pytest.fixture
    def workflow_with_mock_agent(self, tmp_path):
        config = _config(agent_mode="custom", dry_run=False)
        workflow = RedTeamWorkflow(config, "test_app", tmp_path)
        workflow.agent = MagicMock()
        return workflow

    def test_custom_path_logs_neutral_completion_phrasing(
        self, workflow_with_mock_agent, caplog
    ):
        workflow_with_mock_agent.agent.run.return_value = {"status": "completed"}
        with caplog.at_level("INFO", logger="MobileCyBench"):
            workflow_with_mock_agent.run_agent()

        messages = [r.message for r in caplog.records]
        assert "Agent run finished: status=completed" in messages
        assert not any("Agent completed with status:" in m for m in messages)
        assert not any("Agent execution completed:" in m for m in messages)

    def test_custom_path_logs_neutral_timeout_phrasing(
        self, workflow_with_mock_agent, caplog
    ):
        workflow_with_mock_agent.agent.run.return_value = {"status": "timeout"}
        with caplog.at_level("INFO", logger="MobileCyBench"):
            workflow_with_mock_agent.run_agent()

        messages = [r.message for r in caplog.records]
        assert "Agent run finished: status=timeout" in messages
        # No self-contradicting "Agent completed ... timeout" survives.
        assert not any("Agent completed" in m and "timeout" in m for m in messages)


class TestWorkflowRuntimeCleanup:
    def test_cleanup_runs_app_cleanup_script_when_present(self, tmp_path):
        app_dir = tmp_path / "apps" / "test_app"
        app_dir.mkdir(parents=True)
        (app_dir / "cleanup.sh").write_text("#!/usr/bin/env bash\n")

        workflow = RedTeamWorkflow(_config(), "test_app", tmp_path)

        with patch.object(workflow, "_stop_ssrf_listener"), patch(
            "workflows.base.subprocess.run"
        ) as mock_run:
            workflow.cleanup()

        mock_run.assert_called_once_with(
            ["bash", str(app_dir / "cleanup.sh")],
            cwd=app_dir,
            timeout=60,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_cleanup_stops_ssrf_listener(self, tmp_path):
        app_dir = tmp_path / "apps" / "test_app"
        app_dir.mkdir(parents=True)

        workflow = RedTeamWorkflow(_config(), "test_app", tmp_path)

        with patch.object(workflow, "_stop_ssrf_listener") as mock_stop:
            workflow.cleanup()

        mock_stop.assert_called_once()

    def test_stop_ssrf_listener_stops_only_when_running(self, tmp_path):
        workflow = RedTeamWorkflow(_config(), "test_app", tmp_path)

        with patch(
            "utils.ssrf_utils.is_ssrf_listener_running", return_value=True
        ), patch("utils.ssrf_utils.stop_ssrf_listener", return_value=True) as mock_stop:
            workflow._stop_ssrf_listener()

        mock_stop.assert_called_once()

    def test_stop_ssrf_listener_skips_when_not_running(self, tmp_path):
        workflow = RedTeamWorkflow(_config(), "test_app", tmp_path)

        with patch(
            "utils.ssrf_utils.is_ssrf_listener_running", return_value=False
        ), patch("utils.ssrf_utils.stop_ssrf_listener") as mock_stop:
            workflow._stop_ssrf_listener()

        mock_stop.assert_not_called()

    def test_cleanup_clears_active_backend_marker(self, tmp_path):
        app_dir = tmp_path / "apps" / "test_app"
        app_dir.mkdir(parents=True)
        (app_dir / "cleanup.sh").write_text("#!/usr/bin/env bash\n")

        workflow = RedTeamWorkflow(_config(), "test_app", tmp_path)
        state_file = workflow._backend_runtime_state_file()
        state_file.write_text("test_app\n")

        with patch(
            "workflows.base.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=["bash", str(app_dir / "cleanup.sh")],
                returncode=0,
                stdout="",
                stderr="",
            ),
        ):
            workflow.cleanup()

        assert not state_file.exists()

    def test_cleanup_preserves_active_backend_marker_on_failed_cleanup(self, tmp_path):
        app_dir = tmp_path / "apps" / "test_app"
        app_dir.mkdir(parents=True)
        (app_dir / "cleanup.sh").write_text("#!/usr/bin/env bash\n")

        workflow = RedTeamWorkflow(_config(), "test_app", tmp_path)
        state_file = workflow._backend_runtime_state_file()
        state_file.write_text("test_app\n")

        with patch(
            "workflows.base.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=["bash", str(app_dir / "cleanup.sh")],
                returncode=1,
                stdout="",
                stderr="boom",
            ),
        ):
            workflow.cleanup()

        assert state_file.exists()
        assert state_file.read_text().strip() == "test_app"

    def test_cleanup_continues_after_emulator_stop_failure(self, tmp_path):
        app_dir = tmp_path / "apps" / "test_app"
        codebase_dir = app_dir / "codebase"
        agent_codebase = app_dir / "agent_codebase"
        codebase_dir.mkdir(parents=True)
        agent_codebase.mkdir(parents=True)

        workflow = RedTeamWorkflow(_config(), "test_app", tmp_path)
        workflow.emulator = MagicMock()
        workflow.emulator.stop.side_effect = RuntimeError("ADB reset failed")
        workflow.agent_env = MagicMock()

        with patch("utils.git_utils.git_restore_clean") as mock_restore:
            workflow.cleanup()

        workflow.agent_env.cleanup.assert_called_once()
        mock_restore.assert_called_once_with(codebase_dir)
        assert not agent_codebase.exists()

    def test_restart_runtime_marks_backend_active_before_install(self, tmp_path):
        app_dir = tmp_path / "apps" / "test_app"
        app_dir.mkdir(parents=True)
        (app_dir / "docker-compose.yaml").write_text("services: {}\n")

        workflow = RedTeamWorkflow(_config(), "test_app", tmp_path)
        workflow.emulator = _StubEmulator()

        with patch("utils.emulator_certs.inject_system_ca"), patch(
            "utils.setup_utils.install_app_and_setup_backend"
        ), patch(
            "workflows.base.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=["docker", "compose", "down", "-v"],
                returncode=0,
                stdout="",
                stderr="",
            ),
        ):
            workflow._restart_runtime(Path("apk") / "test_app.apk")

        assert workflow._backend_runtime_state_file().read_text().strip() == "test_app"

    def test_preflight_cleanup_propagates_stale_cleanup_failure(self, tmp_path):
        stale_app_dir = tmp_path / "apps" / "stale_app"
        current_app_dir = tmp_path / "apps" / "test_app"
        stale_app_dir.mkdir(parents=True)
        current_app_dir.mkdir(parents=True)
        (stale_app_dir / "cleanup.sh").write_text("#!/usr/bin/env bash\n")
        (current_app_dir / "cleanup.sh").write_text("#!/usr/bin/env bash\n")

        workflow = RedTeamWorkflow(_config(), "test_app", tmp_path)
        workflow._backend_runtime_state_file().write_text("stale_app\n")

        # Network creation runs first; mock so the test stays a unit test
        # (otherwise it would hit the real Docker daemon in CI).
        with _patch_agent_container(), patch(
            "workflows.base.subprocess.run",
            side_effect=subprocess.CalledProcessError(
                1, ["bash", str(stale_app_dir / "cleanup.sh")], "", "boom"
            ),
        ):
            with pytest.raises(subprocess.CalledProcessError):
                workflow._preflight_cleanup_app_runtime()

    def test_preflight_cleanup_stops_stale_ssrf_listener(self, tmp_path):
        app_dir = tmp_path / "apps" / "test_app"
        app_dir.mkdir(parents=True)

        workflow = RedTeamWorkflow(_config(), "test_app", tmp_path)

        with patch.object(
            workflow, "_stop_ssrf_listener"
        ) as mock_stop, _patch_agent_container():
            workflow._preflight_cleanup_app_runtime()

        mock_stop.assert_called_once()

    def test_preflight_cleanup_creates_shared_net_before_cleanup(self, tmp_path):
        """_preflight_cleanup_app_runtime must create shared_net BEFORE running
        cleanup.sh / start_runtime.sh, otherwise apps with `external: true`
        compose networks fail on first run on a clean Docker daemon (R2.19).
        """
        app_dir = tmp_path / "apps" / "test_app"
        app_dir.mkdir(parents=True)
        (app_dir / "cleanup.sh").write_text("#!/usr/bin/env bash\n")

        workflow = RedTeamWorkflow(_config(), "test_app", tmp_path)

        call_order: list[str] = []

        def fake_create_network(name: str, **kwargs) -> None:
            call_order.append(f"create_network:{name}")

        def fake_run(*args, **kwargs):
            # subprocess.run is invoked with positional args=(cmd_list,) for the
            # cleanup.sh shell-out. Record the call.
            cmd = args[0] if args else kwargs.get("args", [])
            if isinstance(cmd, list) and len(cmd) >= 2 and cmd[0] == "bash":
                call_order.append("cleanup.sh")
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="", stderr=""
            )

        with _patch_agent_container(create_network=fake_create_network), patch(
            "workflows.base.subprocess.run", side_effect=fake_run
        ):
            workflow._preflight_cleanup_app_runtime()

        # Network must be created before cleanup.sh runs.
        assert (
            call_order[0] == "create_network:shared_net"
        ), f"create_docker_network('shared_net') must be called first, got order: {call_order}"
        assert (
            "cleanup.sh" in call_order
        ), "cleanup.sh should still run after network create"

    def test_ensure_docker_networks_creates_shared_and_agent_nets(self, tmp_path):
        """_ensure_docker_networks creates shared_net and agent_net (internal=True)
        before any app's compose runs.
        """
        from unittest.mock import call

        workflow = RedTeamWorkflow(_config(), "test_app", tmp_path)

        mock_create = MagicMock()
        with _patch_agent_container(create_network=mock_create):
            workflow._ensure_docker_networks()

        assert mock_create.call_args_list == [
            call("shared_net"),
            call("agent_net", internal=True),
        ]

    def test_skip_guard_passes_when_compose_declares_agent_net(self, tmp_path):
        """App with a backend that joined agent_net is allowed through."""
        app_dir = tmp_path / "apps" / "pilot_app"
        app_dir.mkdir(parents=True)
        (app_dir / "docker-compose.yml").write_text(
            "services:\n  tls_proxy:\n    networks: [agent_net]\n"
        )
        workflow = RedTeamWorkflow(_config(), "pilot_app", tmp_path)

        with _patch_agent_container():
            workflow._ensure_docker_networks()  # must not raise

    def test_skip_guard_passes_when_no_compose_file(self, tmp_path):
        """App with no backend (no compose) has nothing to reach — allowed."""
        (tmp_path / "apps" / "no_backend").mkdir(parents=True)
        workflow = RedTeamWorkflow(_config(), "no_backend", tmp_path)

        with _patch_agent_container():
            workflow._ensure_docker_networks()  # must not raise

    def test_skip_guard_fails_when_compose_missing_agent_net(self, tmp_path):
        """App backend on shared_net only is unreachable from the agent — fail fast."""
        app_dir = tmp_path / "apps" / "legacy_app"
        app_dir.mkdir(parents=True)
        (app_dir / "docker-compose.yml").write_text(
            "services:\n  backend:\n    networks: [shared_net]\n"
        )
        workflow = RedTeamWorkflow(_config(), "legacy_app", tmp_path)

        with _patch_agent_container(), pytest.raises(
            RuntimeError, match="not on agent_net"
        ):
            workflow._ensure_docker_networks()

    def test_restart_runtime_resets_compose_volumes_before_install(self, tmp_path):
        app_dir = tmp_path / "apps" / "test_app"
        app_dir.mkdir(parents=True)
        (app_dir / "docker-compose.yaml").write_text("services: {}\n")

        workflow = RedTeamWorkflow(_config(), "test_app", tmp_path)
        workflow.emulator = _StubEmulator()

        with patch("utils.emulator_certs.inject_system_ca"), patch(
            "utils.setup_utils.install_app_and_setup_backend"
        ) as mock_install, patch(
            "workflows.base.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=["docker", "compose", "down", "-v"],
                returncode=0,
                stdout="",
                stderr="",
            ),
        ) as mock_run:
            workflow._restart_runtime(Path("apk") / "test_app.apk")

        mock_run.assert_called_once_with(
            ["docker", "compose", "down", "-v"],
            cwd=app_dir,
            timeout=60,
            capture_output=True,
            text=True,
            check=False,
        )
        mock_install.assert_called_once()


class TestResolveAdditionalContext:
    """`additional_system_prompt` is appended to per-app `metadata.additional_info`.

    Field has been in the RunnerConfig schema since #290 (2025-10) but had no
    live reader on main since #605 (2026-02) dropped the runner.py wiring.
    These tests pin the restored behavior so it doesn't silently regress.

    Tests target `_resolve_additional_context` directly (rather than the full
    `setup_agent` path) so the assertions stay focused on prompt context
    composition instead of agent/provider setup.
    """

    def _workflow(self, tmp_path, additional_system_prompt=None):
        app_dir = tmp_path / "apps" / "test_app"
        app_dir.mkdir(parents=True)
        (app_dir / "metadata.json").write_text("{}")
        return RedTeamWorkflow(
            _config(additional_system_prompt=additional_system_prompt),
            "test_app",
            tmp_path,
        )

    def test_appends_additional_system_prompt_to_metadata_additional_info(
        self, tmp_path
    ):
        wf = self._workflow(tmp_path, additional_system_prompt="HINT: look at IPC")
        wf.metadata = {"additional_info": "App ships with seeded user"}
        # Ordering is load-bearing: per-app context first (threat model
        # framing), runtime knob (hint) second.
        assert (
            wf._resolve_additional_context()
            == "App ships with seeded user\n\nHINT: look at IPC"
        )

    def test_returns_additional_system_prompt_alone_when_no_metadata_info(
        self, tmp_path
    ):
        wf = self._workflow(tmp_path, additional_system_prompt="HINT: look at IPC")
        wf.metadata = {}
        assert wf._resolve_additional_context() == "HINT: look at IPC"

    def test_returns_metadata_unchanged_when_no_additional_system_prompt(
        self, tmp_path
    ):
        wf = self._workflow(tmp_path)  # additional_system_prompt = None
        wf.metadata = {"additional_info": "App ships with seeded user"}
        assert wf._resolve_additional_context() == "App ships with seeded user"

    def test_returns_none_when_neither_set(self, tmp_path):
        wf = self._workflow(tmp_path)
        wf.metadata = {}
        assert wf._resolve_additional_context() is None

    def test_empty_string_additional_system_prompt_is_treated_as_unset(self, tmp_path):
        # `""` and `None` should behave the same — empty strings in JSON
        # config commonly mean "no value", and we should not paste an empty
        # paragraph onto the prompt either way.
        wf = self._workflow(tmp_path, additional_system_prompt="")
        wf.metadata = {"additional_info": "App ships with seeded user"}
        assert wf._resolve_additional_context() == "App ships with seeded user"


class _StubEmulator:
    def restart(self) -> None:
        pass

    def wait_until_ready(self, timeout) -> None:
        del timeout

    def setup_port_forwards(self, app_dir) -> None:
        del app_dir
