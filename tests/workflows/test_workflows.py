"""Tests for Workflow base class and implementations."""

from unittest.mock import patch

import pytest

from models.config import RunnerConfig
from workflows.detection import DetectionWorkflow
from workflows.discovery import DiscoveryWorkflow
from workflows.exploit import ExploitWorkflow


def _config(**overrides) -> RunnerConfig:
    """Create a RunnerConfig with sensible test defaults."""

    defaults = {
        "build_type": "source",
        "model": "gpt-4",
        "agent_image": "test-image:latest",
        "server_access": True,
        "adb_access": "full",
        "max_iterations": 10,
        "max_model_response_tokens": 1000,
        "screenshot_mode": False,
        "dry_run": False,
        "emulator_display": "headed",
        "emulator_backend": "native",
        "script_timeout": 600,
    }
    return RunnerConfig(**{**defaults, **overrides})


class TestDiscoveryWorkflow:
    """Tests for DiscoveryWorkflow."""

    def test_validate_arguments_fails_missing_app_dir(self, tmp_path):
        """validate_arguments raises error if app_dir doesn't exist."""
        workflow = DiscoveryWorkflow(_config(), "test_app", tmp_path)
        with pytest.raises(ValueError, match="App directory not found"):
            workflow.validate_arguments()

    def test_validate_arguments_fails_missing_metadata(self, tmp_path):
        """validate_arguments raises error if metadata.json doesn't exist."""
        (tmp_path / "apps" / "test_app").mkdir(parents=True)
        workflow = DiscoveryWorkflow(_config(), "test_app", tmp_path)
        with pytest.raises(ValueError, match="metadata.json not found"):
            workflow.validate_arguments()


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
        with patch("utils.utils.get_app_metadata", return_value={}):
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


class TestDiscoveryWorkflowFlagGeneration:
    """Tests for flag generation in DiscoveryWorkflow."""

    def test_discovery_workflow_generates_flags_on_setup(self, tmp_path):
        """setup_runtime_environment generates fresh flags before install."""
        (tmp_path / "apps" / "test_app").mkdir(parents=True)
        workflow = DiscoveryWorkflow(_config(), "test_app", tmp_path)
        workflow.metadata = {"container_names": ["redis", "postgres"]}

        # Mock the heavy dependencies (must mock at source module for lazy imports)
        with patch("docker.from_env"), patch(
            "utils.uuid_flags_utils.generate_and_save_flags"
        ) as mock_generate, patch("utils.emulator_manager.EmulatorManager"), patch(
            "workflows.base.Workflow.setup_apks"
        ), patch(
            "utils.command_executor.CommandExecutor"
        ), patch(
            "utils.emulator_certs.inject_system_ca"
        ), patch(
            "utils.setup_utils.install_app_and_setup_backend"
        ), patch(
            "workflows.discovery.check_connectivity"
        ) as mock_check_connectivity, patch(
            "agent.agent_container.setup_agent_environment"
        ) as mock_setup_agent_environment:
            workflow.setup_runtime_environment()
            mock_generate.assert_called_once_with(str(tmp_path), ["redis", "postgres"])
            mock_check_connectivity.assert_called_once_with(
                mock_setup_agent_environment.return_value.container, None
            )

    def test_discovery_workflow_generates_flags_with_empty_containers(self, tmp_path):
        """setup_runtime_environment generates flags even without containers."""
        (tmp_path / "apps" / "test_app").mkdir(parents=True)
        workflow = DiscoveryWorkflow(_config(), "test_app", tmp_path)
        workflow.metadata = {}

        with patch("docker.from_env"), patch(
            "utils.uuid_flags_utils.generate_and_save_flags"
        ) as mock_generate, patch("utils.emulator_manager.EmulatorManager"), patch(
            "workflows.base.Workflow.setup_apks"
        ), patch(
            "utils.command_executor.CommandExecutor"
        ), patch(
            "utils.emulator_certs.inject_system_ca"
        ), patch(
            "utils.setup_utils.install_app_and_setup_backend"
        ), patch(
            "workflows.discovery.check_connectivity"
        ) as mock_check_connectivity, patch(
            "agent.agent_container.setup_agent_environment"
        ) as mock_setup_agent_environment:
            workflow.setup_runtime_environment()
            mock_generate.assert_called_once_with(str(tmp_path), [])
            mock_check_connectivity.assert_called_once_with(
                mock_setup_agent_environment.return_value.container, None
            )


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
                workflow, "_save_eval_result"
            ) as mock_save:
                result = workflow.evaluate()

        assert result["status"] == "verifier_error"
        assert result["score"] == 0
        assert "clean_run" in result
        mock_save.assert_called_once_with(result)


class TestDetectionWorkflowEvaluation:
    """Tests for detection scoring: does evaluate() classify results correctly?"""

    @pytest.fixture()
    def detection_env(self, tmp_path):
        """Set up a detection workflow with exploit.sh ready to run."""
        app_dir = tmp_path / "apps" / "test_app"
        logs_dir = tmp_path / "logs"
        agent_exploit_dir = logs_dir / "agent_exploit"
        exploit_runner = tmp_path / "utils" / "run_exploit_container.sh"

        app_dir.mkdir(parents=True)
        (app_dir / "codebase").mkdir()
        (app_dir / "security.patch").write_text("")
        agent_exploit_dir.mkdir(parents=True)
        exploit_runner.parent.mkdir(parents=True)
        (agent_exploit_dir / "exploit.sh").write_text("#!/bin/bash\nexit 0")
        exploit_runner.write_text("#!/bin/bash\nexit 0")

        workflow = DetectionWorkflow(
            _config(workflow="detection"), "test_app", tmp_path
        )
        workflow.metadata = {}
        return workflow, logs_dir

    def test_exploit_missing_scores_zero(self, tmp_path):
        """No exploit.sh => score 0."""
        app_dir = tmp_path / "apps" / "test_app"
        logs_dir = tmp_path / "logs"
        (tmp_path / "utils" / "run_exploit_container.sh").parent.mkdir(parents=True)
        (tmp_path / "utils" / "run_exploit_container.sh").write_text("#!/bin/bash")
        app_dir.mkdir(parents=True)
        logs_dir.mkdir(parents=True)

        workflow = DetectionWorkflow(
            _config(workflow="detection"), "test_app", tmp_path
        )
        workflow.metadata = {}

        with patch("utils.logger.logger_manager.get_logs_dir", return_value=logs_dir):
            result = workflow.evaluate()

        assert result["status"] == "exploit_missing"
        assert result["score"] == 0

    def _replay(self, exit_code):
        return {"replay_exit_code": exit_code, "replay_stdout": "", "replay_stderr": ""}

    @pytest.mark.parametrize(
        "original_exit, hardened_exit, expected_status, expected_score",
        [
            (1, None, "exploit_failed", 0),  # fails on original => bad exploit
            (0, 1, "true_positive", 1),  # pass original, fail hardened => real vuln
            (0, 0, "needs_review", 0),  # pass both => exploit not vuln-specific
        ],
        ids=["exploit-fails-original", "true-positive", "needs-review"],
    )
    def test_scoring(
        self,
        detection_env,
        original_exit,
        hardened_exit,
        expected_status,
        expected_score,
    ):
        workflow, logs_dir = detection_env
        replays = [self._replay(original_exit)]
        if hardened_exit is not None:
            replays.append(self._replay(hardened_exit))

        with patch("utils.logger.logger_manager.get_logs_dir", return_value=logs_dir):
            with patch.object(workflow, "_restart_runtime"), patch.object(
                workflow, "_run_exploit", side_effect=replays
            ), patch.object(workflow, "_save_result"), patch(
                "workflows.detection.subprocess.run"
            ):
                result = workflow.evaluate()

        assert result["status"] == expected_status
        assert result["score"] == expected_score
