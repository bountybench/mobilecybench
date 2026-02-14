"""Tests for runner.py - Workflow-based runner."""

from unittest.mock import patch

import pytest

from models.config import CustomAgentConfig, EnvironmentConfig, RunnerConfig
from runner import create_workflow, main, run
from workflows import DiscoveryWorkflow, ExploitWorkflow


@pytest.fixture
def base_config():
    """Base configuration for testing."""

    env = EnvironmentConfig(
        server_access=True,
        build_type="source",
        adb_access="full",
        model="gpt-4",
        screenshot_mode=False,
        headless_mode=True,
        dry_run=False,
        agent_environment_image="test-image:latest",
        docker_mode=False,
        workflow="discovery",
    )

    agents = {
        "custom": CustomAgentConfig(
            max_iterations=10,
            max_kali_message_tokens=1000,
            max_model_response_tokens=1000,
            max_context_length=10000,
            model="gpt-4",
            agent_image="test-image",
        )
    }

    return RunnerConfig(environment=env, agents=agents)


@pytest.fixture
def exploit_config(base_config):
    """Configuration for exploit workflow."""
    return RunnerConfig(**{**base_config.model_dump(), "workflow": "exploit"})


class TestCreateWorkflow:
    """Tests for workflow selection logic."""

    def test_creates_discovery_workflow_by_default(self, base_config, tmp_path):
        """Default workflow type is DiscoveryWorkflow."""
        workflow = create_workflow(base_config, "test_app", tmp_path)
        assert isinstance(workflow, DiscoveryWorkflow)

    def test_creates_exploit_workflow_when_configured(self, exploit_config, tmp_path):
        """ExploitWorkflow is created when config.workflow == 'exploit'."""
        workflow = create_workflow(exploit_config, "test_app", tmp_path)
        assert isinstance(workflow, ExploitWorkflow)


class TestRun:
    """Tests for run() - focus on error handling and cleanup guarantees."""

    def test_success_returns_zero(self, base_config, tmp_path):
        """Successful execution returns exit code 0."""
        with patch("runner.ensure_app_submodule"), patch.object(
            DiscoveryWorkflow, "validate_arguments"
        ), patch.object(DiscoveryWorkflow, "setup_runtime_environment"), patch.object(
            DiscoveryWorkflow, "setup_agent"
        ), patch.object(
            DiscoveryWorkflow, "run_agent", return_value={"status": "completed"}
        ), patch.object(
            DiscoveryWorkflow, "evaluate", return_value={"score": 1}
        ), patch.object(
            DiscoveryWorkflow, "cleanup"
        ):

            result = run(base_config, "test_app", tmp_path)
            assert result == 0

    def test_validation_error_returns_one_and_still_cleans_up(
        self, base_config, tmp_path
    ):
        """Validation error returns exit code 1 but cleanup still runs."""
        with patch("runner.ensure_app_submodule"), patch.object(
            DiscoveryWorkflow,
            "validate_arguments",
            side_effect=ValueError("App directory not found"),
        ), patch.object(DiscoveryWorkflow, "cleanup") as mock_cleanup:

            result = run(base_config, "test_app", tmp_path)
            assert result == 1
            mock_cleanup.assert_called_once()

    def test_cleanup_called_even_when_agent_crashes(self, base_config, tmp_path):
        """Cleanup is called even when agent fails mid-execution."""
        with patch("runner.ensure_app_submodule"), patch.object(
            DiscoveryWorkflow, "validate_arguments"
        ), patch.object(DiscoveryWorkflow, "setup_runtime_environment"), patch.object(
            DiscoveryWorkflow, "setup_agent"
        ), patch.object(
            DiscoveryWorkflow, "run_agent", side_effect=Exception("Agent crashed")
        ), patch.object(
            DiscoveryWorkflow, "cleanup"
        ) as mock_cleanup:

            run(base_config, "test_app", tmp_path)
            mock_cleanup.assert_called_once()

    def test_dry_run_skips_agent_execution(self, base_config, tmp_path):
        """Dry run mode runs interactive shell instead of agent."""
        dry_run_config = RunnerConfig(**{**base_config.model_dump(), "dry_run": True})

        with patch("runner.ensure_app_submodule"), patch.object(
            DiscoveryWorkflow, "validate_arguments"
        ), patch.object(DiscoveryWorkflow, "setup_runtime_environment"), patch.object(
            DiscoveryWorkflow, "setup_agent"
        ) as mock_setup_agent, patch.object(
            DiscoveryWorkflow, "run_agent"
        ) as mock_run_agent, patch.object(
            DiscoveryWorkflow, "cleanup"
        ), patch(
            "runner.run_interactive_shell", return_value={"status": "completed"}
        ):

            run(dry_run_config, "test_app", tmp_path)

            mock_setup_agent.assert_not_called()
            mock_run_agent.assert_not_called()


class TestMain:
    """Tests for CLI entry point."""

    def test_missing_config_file_returns_one(self, tmp_path, monkeypatch):
        """Missing config file returns exit code 1."""
        monkeypatch.chdir(tmp_path)

        with patch(
            "sys.argv", ["runner.py", "test_app", "--config", "nonexistent.json"]
        ):
            result = main()
            assert result == 1
