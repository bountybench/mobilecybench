"""Tests for Workflow base class and implementations."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from models.config import RunnerConfig
from workflows.exploit import ExploitWorkflow


def _config(**overrides) -> RunnerConfig:
    """Create a RunnerConfig with sensible test defaults."""

    defaults = {
        "build_type": "source",
        "model": "gpt-4",
        "agent_image": "test-image:latest",
        "max_iterations": 10,
        "max_model_response_tokens": 1000,
        "screenshot_mode": False,
        "dry_run": False,
        "emulator_display": "headed",
        "emulator_backend": "native",
        "network_mode": "restricted",
        "script_timeout": 600,
        "synthetic_vuln_id": "vuln_0",
    }
    return RunnerConfig(**{**defaults, **overrides})


class TestExploitWorkflow:
    """Tests for ExploitWorkflow."""

    def test_validate_arguments_fails_missing_app_dir(self, tmp_path):
        """validate_arguments raises error if app_dir doesn't exist."""
        workflow = ExploitWorkflow(_config(workflow="exploit"), "test_app", tmp_path)
        with pytest.raises(ValueError, match="App directory not found"):
            workflow.validate_arguments()

    def test_validate_arguments_fails_missing_vuln_dir(self, tmp_path):
        """validate_arguments raises error if target vulnerability dir doesn't exist."""
        app_dir = tmp_path / "apps" / "test_app"
        app_dir.mkdir(parents=True)
        (app_dir / "metadata.json").write_text("{}")
        workflow = ExploitWorkflow(_config(workflow="exploit"), "test_app", tmp_path)
        with pytest.raises(ValueError, match="Vulnerability directory not found"):
            workflow.validate_arguments()

    def test_validate_arguments_fails_missing_verify_files(self, tmp_path):
        """validate_arguments raises error if verify_files doesn't exist."""
        app_dir = tmp_path / "apps" / "test_app"
        app_dir.mkdir(parents=True)
        (app_dir / "metadata.json").write_text("{}")
        (app_dir / "synthetic_vulnerabilities" / "vuln_0").mkdir(parents=True)
        workflow = ExploitWorkflow(_config(workflow="exploit"), "test_app", tmp_path)
        with pytest.raises(ValueError, match="verify_files not found"):
            workflow.validate_arguments()

    def test_validate_arguments_fails_missing_patch(self, tmp_path):
        """validate_arguments raises error if vulnerability.patch doesn't exist."""
        app_dir = tmp_path / "apps" / "test_app"
        app_dir.mkdir(parents=True)
        (app_dir / "metadata.json").write_text("{}")
        vuln_dir = app_dir / "synthetic_vulnerabilities" / "vuln_0"
        (vuln_dir / "verify_files").mkdir(parents=True)
        workflow = ExploitWorkflow(_config(workflow="exploit"), "test_app", tmp_path)
        with pytest.raises(ValueError, match="vulnerability.patch not found"):
            workflow.validate_arguments()

    def test_validate_arguments_uses_configurable_vuln_id(self, tmp_path):
        """validate_arguments checks for the configured vuln_id, not hardcoded 'vuln_0'."""
        app_dir = tmp_path / "apps" / "test_app"
        app_dir.mkdir(parents=True)
        (app_dir / "metadata.json").write_text("{}")
        vuln_dir = app_dir / "synthetic_vulnerabilities" / "vuln_1"
        (vuln_dir / "verify_files").mkdir(parents=True)
        (vuln_dir / "vulnerability.patch").write_text("patch content")
        config = _config(workflow="exploit", synthetic_vuln_id="vuln_1")
        workflow = ExploitWorkflow(config, "test_app", tmp_path)
        workflow.validate_arguments()

    def test_validate_arguments_fails_when_vuln_id_dir_missing(self, tmp_path):
        """validate_arguments fails if the specified vuln_id directory doesn't exist."""
        app_dir = tmp_path / "apps" / "test_app"
        app_dir.mkdir(parents=True)
        (app_dir / "metadata.json").write_text("{}")
        vuln_dir = app_dir / "synthetic_vulnerabilities" / "vuln_0"
        (vuln_dir / "verify_files").mkdir(parents=True)
        (vuln_dir / "vulnerability.patch").write_text("patch content")
        config = _config(workflow="exploit", synthetic_vuln_id="vuln_1")
        workflow = ExploitWorkflow(config, "test_app", tmp_path)
        with pytest.raises(
            ValueError, match="Vulnerability directory not found.*vuln_1"
        ):
            workflow.validate_arguments()


class TestExploitWorkflowEvaluation:
    """Tests for exploit evaluation result classification."""

    def test_evaluate_returns_verifier_error_when_clean_verify_exits_gt_one(
        self, tmp_path
    ):
        """Clean-run verifier errors must not be scored as true positives."""
        app_dir = tmp_path / "apps" / "test_app"
        logs_dir = tmp_path / "logs"
        agent_exploit_dir = logs_dir / "agent_exploit"
        exploit_runner = tmp_path / "utils" / "run_exploit_container.sh"
        agent_exploit_dir.mkdir(parents=True)
        exploit_runner.parent.mkdir(parents=True)
        (agent_exploit_dir / "exploit.sh").write_text("#!/bin/bash\nexit 0")
        exploit_runner.write_text("#!/bin/bash\nexit 0")
        app_dir.mkdir(parents=True)

        workflow = ExploitWorkflow(_config(workflow="exploit"), "test_app", tmp_path)
        workflow.metadata = {}

        with patch("utils.logger.logger_manager.get_logs_dir", return_value=logs_dir):
            with patch.object(workflow, "_restart_runtime"), patch.object(
                workflow,
                "_run_exploit",
                side_effect=[
                    {
                        "replay_exit_code": 0,
                        "replay_stdout": "",
                        "replay_stderr": "",
                    },
                    {
                        "replay_exit_code": 0,
                        "replay_stdout": "",
                        "replay_stderr": "",
                    },
                ],
            ), patch.object(
                workflow,
                "_run_verify",
                side_effect=[
                    {
                        "exit_code": 0,
                        "stdout": "",
                        "stderr": "",
                        "status": "vulnerable",
                    },
                    {
                        "exit_code": 2,
                        "stdout": "",
                        "stderr": "adb failure",
                        "status": "verifier_error",
                    },
                ],
            ), patch.object(
                workflow, "_save_result"
            ) as mock_save:
                result = workflow.evaluate()

        assert result["status"] == "verifier_error"
        assert result["score"] == 0
        assert "clean_run" in result
        mock_save.assert_called_once_with(result)


class TestWorkflowRuntimeCleanup:
    def test_cleanup_runs_app_cleanup_script_when_present(self, tmp_path):
        app_dir = tmp_path / "apps" / "test_app"
        app_dir.mkdir(parents=True)
        (app_dir / "cleanup.sh").write_text("#!/usr/bin/env bash\n")

        workflow = ExploitWorkflow(_config(workflow="exploit"), "test_app", tmp_path)

        with patch("workflows.base.subprocess.run") as mock_run:
            workflow.cleanup()

        mock_run.assert_called_once_with(
            ["bash", str(app_dir / "cleanup.sh")],
            cwd=app_dir,
            timeout=60,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_cleanup_clears_active_backend_marker(self, tmp_path):
        app_dir = tmp_path / "apps" / "test_app"
        app_dir.mkdir(parents=True)
        (app_dir / "cleanup.sh").write_text("#!/usr/bin/env bash\n")

        workflow = ExploitWorkflow(_config(workflow="exploit"), "test_app", tmp_path)
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

        workflow = ExploitWorkflow(_config(workflow="exploit"), "test_app", tmp_path)
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

        workflow = ExploitWorkflow(_config(workflow="exploit"), "test_app", tmp_path)
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

        workflow = ExploitWorkflow(_config(workflow="exploit"), "test_app", tmp_path)
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

        workflow = ExploitWorkflow(_config(workflow="exploit"), "test_app", tmp_path)
        workflow._backend_runtime_state_file().write_text("stale_app\n")

        # Network creation runs first; mock so the test stays a unit test
        # (otherwise it would hit the real Docker daemon in CI).
        with patch("agent.agent_container.create_docker_network"), patch(
            "workflows.base.subprocess.run",
            side_effect=subprocess.CalledProcessError(
                1, ["bash", str(stale_app_dir / "cleanup.sh")], "", "boom"
            ),
        ):
            with pytest.raises(subprocess.CalledProcessError):
                workflow._preflight_cleanup_app_runtime()

    def test_preflight_cleanup_creates_shared_net_before_cleanup(self, tmp_path):
        """_preflight_cleanup_app_runtime must create shared_net BEFORE running
        cleanup.sh / start_runtime.sh, otherwise apps with `external: true`
        compose networks fail on first run on a clean Docker daemon (R2.19).
        """
        app_dir = tmp_path / "apps" / "test_app"
        app_dir.mkdir(parents=True)
        (app_dir / "cleanup.sh").write_text("#!/usr/bin/env bash\n")

        workflow = ExploitWorkflow(_config(workflow="exploit"), "test_app", tmp_path)

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

        with patch(
            "agent.agent_container.create_docker_network",
            side_effect=fake_create_network,
        ), patch("workflows.base.subprocess.run", side_effect=fake_run):
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

        workflow = ExploitWorkflow(_config(workflow="exploit"), "test_app", tmp_path)

        with patch("agent.agent_container.create_docker_network") as mock_create:
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
        workflow = ExploitWorkflow(_config(workflow="exploit"), "pilot_app", tmp_path)

        with patch("agent.agent_container.create_docker_network"):
            workflow._ensure_docker_networks()  # must not raise

    def test_skip_guard_passes_when_no_compose_file(self, tmp_path):
        """App with no backend (no compose) has nothing to reach — allowed."""
        (tmp_path / "apps" / "no_backend").mkdir(parents=True)
        workflow = ExploitWorkflow(_config(workflow="exploit"), "no_backend", tmp_path)

        with patch("agent.agent_container.create_docker_network"):
            workflow._ensure_docker_networks()  # must not raise

    def test_skip_guard_fails_when_compose_missing_agent_net(self, tmp_path):
        """App backend on shared_net only is unreachable from the agent — fail fast."""
        app_dir = tmp_path / "apps" / "legacy_app"
        app_dir.mkdir(parents=True)
        (app_dir / "docker-compose.yml").write_text(
            "services:\n  backend:\n    networks: [shared_net]\n"
        )
        workflow = ExploitWorkflow(_config(workflow="exploit"), "legacy_app", tmp_path)

        with patch("agent.agent_container.create_docker_network"), pytest.raises(
            RuntimeError, match="not on agent_net"
        ):
            workflow._ensure_docker_networks()

    def test_restart_runtime_resets_compose_volumes_before_install(self, tmp_path):
        app_dir = tmp_path / "apps" / "test_app"
        app_dir.mkdir(parents=True)
        (app_dir / "docker-compose.yaml").write_text("services: {}\n")

        workflow = ExploitWorkflow(_config(workflow="exploit"), "test_app", tmp_path)
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
    """`custom_system_prompt` is appended to per-app `metadata.additional_info`.

    Field has been in the RunnerConfig schema since #290 (2025-10) but had no
    live reader on main since #605 (2026-02) dropped the runner.py wiring.
    These tests pin the restored behavior so it doesn't silently regress.

    Tests target `_resolve_additional_context` directly (rather than the full
    `setup_agent` path) because the agent constructors transitively import
    `agent.backend.docker_setup`, which calls `docker.from_env()` at module
    import time and fails under pytest without a live docker daemon.
    """

    def _workflow(self, tmp_path, custom_system_prompt=None):
        app_dir = tmp_path / "apps" / "test_app"
        app_dir.mkdir(parents=True)
        (app_dir / "metadata.json").write_text("{}")
        return ExploitWorkflow(
            _config(workflow="exploit", custom_system_prompt=custom_system_prompt),
            "test_app",
            tmp_path,
        )

    def test_appends_custom_system_prompt_to_metadata_additional_info(self, tmp_path):
        wf = self._workflow(tmp_path, custom_system_prompt="HINT: look at IPC")
        wf.metadata = {"additional_info": "App ships with seeded user"}
        # Ordering is load-bearing: per-app context first (threat model
        # framing), runtime knob (hint) second.
        assert (
            wf._resolve_additional_context()
            == "App ships with seeded user\n\nHINT: look at IPC"
        )

    def test_returns_custom_system_prompt_alone_when_no_metadata_info(self, tmp_path):
        wf = self._workflow(tmp_path, custom_system_prompt="HINT: look at IPC")
        wf.metadata = {}
        assert wf._resolve_additional_context() == "HINT: look at IPC"

    def test_returns_metadata_unchanged_when_no_custom_system_prompt(self, tmp_path):
        wf = self._workflow(tmp_path)  # custom_system_prompt = None
        wf.metadata = {"additional_info": "App ships with seeded user"}
        assert wf._resolve_additional_context() == "App ships with seeded user"

    def test_returns_none_when_neither_set(self, tmp_path):
        wf = self._workflow(tmp_path)
        wf.metadata = {}
        assert wf._resolve_additional_context() is None

    def test_empty_string_custom_system_prompt_is_treated_as_unset(self, tmp_path):
        # `""` and `None` should behave the same — empty strings in JSON
        # config commonly mean "no value", and we should not paste an empty
        # paragraph onto the prompt either way.
        wf = self._workflow(tmp_path, custom_system_prompt="")
        wf.metadata = {"additional_info": "App ships with seeded user"}
        assert wf._resolve_additional_context() == "App ships with seeded user"


class _StubEmulator:
    def restart(self) -> None:
        pass

    def wait_until_ready(self, timeout) -> None:
        del timeout

    def setup_port_forwards(self, app_dir) -> None:
        del app_dir
