"""Tests for Workflow base class and implementations."""

from copy import deepcopy
from unittest.mock import patch

import pytest

from models.config import EnvironmentConfig, RunnerConfig
from workflows.base import Workflow
from workflows.discovery import DiscoveryWorkflow
from workflows.exploit import ExploitWorkflow

DEFAULT_ENVIRONMENT_CONFIG = {
    "server_access": True,
    "build_type": "source",
    "adb_access": "full",
    "agent_environment_image": "cybench/mobilecybench:latest",
    "screenshot_mode": False,
    "headless_mode": False,
    "dry_run": False,
    "docker_mode": False,
    "synthetic_vuln": False,
    "workflow": "discovery",
    "synthetic_vuln_id": "vuln_0",
}

DEFAULT_AGENT_CONFIG = {
    "model": "gpt-4",
    "reasoning_effort": "medium",
    "thinking_budget": 8192,
    "max_iterations": 10,
    "max_context_length": 200000,
    "max_kali_message_tokens": 8192,
    "max_model_response_tokens": 1000,
    "allowed_tools": [
        "execute_command",
        "get_current_ui_state",
        "execute_command_with_ui_state",
    ],
    "custom_system_prompt": None,
}


def build_runner_config(env_overrides=None, agent_overrides=None) -> RunnerConfig:
    """Return a RunnerConfig with optional overrides for tests."""
    env_data = deepcopy(DEFAULT_ENVIRONMENT_CONFIG)
    agent_data = deepcopy(DEFAULT_AGENT_CONFIG)

    if env_overrides:
        env_data.update(env_overrides)
    if agent_overrides:
        agent_data.update(agent_overrides)

    environment = EnvironmentConfig(**env_data)
    return RunnerConfig(environment=environment, agents={"custom": agent_data})


def build_exploit_runner_config(
    env_overrides=None, agent_overrides=None
) -> RunnerConfig:
    """Specialized helper for exploit workflow configs."""
    exploit_overrides = {"workflow": "exploit", "synthetic_vuln": True}
    if env_overrides:
        exploit_overrides.update(env_overrides)
    return build_runner_config(
        env_overrides=exploit_overrides, agent_overrides=agent_overrides
    )


class TestWorkflowBaseClass:
    """Tests for the Workflow abstract base class."""

    def test_workflow_cannot_be_instantiated(self):
        """Workflow is abstract and cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            Workflow()

    def test_workflow_defines_required_methods(self):
        """Workflow defines all required abstract methods."""
        abstract_methods = Workflow.__abstractmethods__
        expected = {
            "validate_arguments",
            "setup_runtime_environment",
            "setup_agent",
            "run_agent",
            "evaluate",
            "cleanup",
        }
        assert abstract_methods == expected


class TestDiscoveryWorkflow:
    """Tests for DiscoveryWorkflow."""

    def test_discovery_workflow_is_workflow_subclass(self):
        """DiscoveryWorkflow inherits from Workflow."""
        assert issubclass(DiscoveryWorkflow, Workflow)

    def test_discovery_workflow_can_be_instantiated(self, tmp_path):
        """DiscoveryWorkflow can be instantiated with required arguments."""

        model = "gpt-4"
        max_iterations = 10

        config = build_runner_config(
            env_overrides={"build_type": "skip-apk"},
            agent_overrides={"model": model, "max_iterations": max_iterations},
        )

        workflow = DiscoveryWorkflow(
            config=config,
            app_name="test_app",
            app_dir=tmp_path,
        )

        assert workflow.app_name == "test_app"
        assert workflow.config.agents["custom"].model == "gpt-4"
        assert workflow.config.agents["custom"].max_iterations == 10
        assert workflow.config.environment.build_type == "skip-apk"
        assert workflow.config.environment.dry_run is False  # default

    def test_discovery_workflow_accepts_all_parameters(self, tmp_path):
        """DiscoveryWorkflow accepts all optional parameters."""

        model = "gpt-4"
        max_iterations = 10

        config = build_runner_config(
            env_overrides={
                "build_type": "download-apk",
                "screenshot_mode": True,
                "dry_run": True,
                "agent_environment_image": "custom-image:latest",
            },
            agent_overrides={"model": model, "max_iterations": max_iterations},
        )

        workflow = DiscoveryWorkflow(
            config=config,
            app_name="test_app",
            app_dir=tmp_path,
            project_root=tmp_path,
        )

        assert workflow.config.environment.build_type == "download-apk"
        assert (
            workflow.config.environment.agent_environment_image == "custom-image:latest"
        )
        assert workflow.project_root == tmp_path
        assert workflow.config.environment.dry_run is True
        assert workflow.config.environment.screenshot_mode is True

    def test_validate_arguments_fails_missing_app_dir(self, tmp_path):
        """validate_arguments raises error if app_dir doesn't exist."""
        non_existent = tmp_path / "does_not_exist"
        config = build_runner_config()
        workflow = DiscoveryWorkflow(
            config=config,
            app_name="test_app",
            app_dir=non_existent,
        )
        with pytest.raises(ValueError, match="App directory not found"):
            workflow.validate_arguments()

    def test_validate_arguments_fails_missing_metadata(self, tmp_path):
        """validate_arguments raises error if metadata.json doesn't exist."""
        config = build_runner_config()
        workflow = DiscoveryWorkflow(
            config=config,
            app_name="test_app",
            app_dir=tmp_path,
        )
        with pytest.raises(ValueError, match="metadata.json not found"):
            workflow.validate_arguments()


class TestExploitWorkflow:
    """Tests for ExploitWorkflow."""

    def test_exploit_workflow_is_workflow_subclass(self):
        """ExploitWorkflow inherits from Workflow."""
        assert issubclass(ExploitWorkflow, Workflow)

    def test_exploit_workflow_can_be_instantiated(self, tmp_path):
        """ExploitWorkflow can be instantiated with required arguments."""
        config = build_exploit_runner_config()
        workflow = ExploitWorkflow(
            config=config,
            app_name="test_app",
            app_dir=tmp_path,
        )
        assert workflow.app_name == "test_app"
        assert workflow.config.agents["custom"].model == "gpt-4"
        assert workflow.config.environment.build_type == "source"  # default
        assert workflow.config.environment.dry_run is False  # default

    def test_validate_arguments_fails_missing_app_dir(self, tmp_path):
        """validate_arguments raises error if app_dir doesn't exist."""
        non_existent = tmp_path / "does_not_exist"
        config = build_exploit_runner_config()
        workflow = ExploitWorkflow(
            config=config,
            app_name="test_app",
            app_dir=non_existent,
        )
        with pytest.raises(ValueError, match="App directory not found"):
            workflow.validate_arguments()

    def test_validate_arguments_fails_missing_vuln_dir(self, tmp_path):
        """validate_arguments raises error if target vulnerability dir doesn't exist."""
        (tmp_path / "metadata.json").write_text("{}")
        config = build_exploit_runner_config()
        workflow = ExploitWorkflow(
            config=config,
            app_name="test_app",
            app_dir=tmp_path,
        )
        with pytest.raises(ValueError, match="Vulnerability directory not found"):
            workflow.validate_arguments()

    def test_validate_arguments_fails_missing_verify_files(self, tmp_path):
        """validate_arguments raises error if verify_files doesn't exist."""
        (tmp_path / "metadata.json").write_text("{}")
        vuln_dir = tmp_path / "synthetic_vulnerabilities" / "vuln_0"
        vuln_dir.mkdir(parents=True)

        config = build_exploit_runner_config()
        workflow = ExploitWorkflow(
            config=config,
            app_name="test_app",
            app_dir=tmp_path,
        )
        with pytest.raises(ValueError, match="verify_files not found"):
            workflow.validate_arguments()

    def test_validate_arguments_fails_missing_patch(self, tmp_path):
        """validate_arguments raises error if vulnerability.patch doesn't exist."""
        (tmp_path / "metadata.json").write_text("{}")
        verify_dir = tmp_path / "synthetic_vulnerabilities" / "vuln_0" / "verify_files"
        verify_dir.mkdir(parents=True)

        config = build_exploit_runner_config()
        workflow = ExploitWorkflow(
            config=config,
            app_name="test_app",
            app_dir=tmp_path,
        )
        with pytest.raises(ValueError, match="vulnerability.patch not found"):
            workflow.validate_arguments()

    def test_validate_arguments_fails_wrong_build_type(self, tmp_path):
        """validate_arguments raises error if build_type is not 'source'."""
        (tmp_path / "metadata.json").write_text("{}")
        vuln_dir = tmp_path / "synthetic_vulnerabilities" / "vuln_0"
        verify_dir = vuln_dir / "verify_files"
        verify_dir.mkdir(parents=True)
        (vuln_dir / "vulnerability.patch").write_text("patch content")

        config = build_exploit_runner_config(
            env_overrides={"build_type": "download-apk"}
        )
        workflow = ExploitWorkflow(
            config=config,
            app_name="test_app",
            app_dir=tmp_path,
        )
        with pytest.raises(
            ValueError, match="requires build_type='source' or 'skip-apk'"
        ):
            workflow.validate_arguments()

    def test_exploit_workflow_stores_vuln_id(self, tmp_path):
        """ExploitWorkflow stores the vuln_id parameter."""
        config = build_exploit_runner_config()
        workflow = ExploitWorkflow(
            config=config,
            app_name="test_app",
            app_dir=tmp_path,
            vuln_id="vuln_1",
        )
        assert workflow.vuln_id == "vuln_1"

    def test_exploit_workflow_vuln_id_defaults_to_vuln_0(self, tmp_path):
        """ExploitWorkflow defaults vuln_id to 'vuln_0'."""
        config = build_exploit_runner_config()
        workflow = ExploitWorkflow(
            config=config,
            app_name="test_app",
            app_dir=tmp_path,
        )
        assert workflow.vuln_id == "vuln_0"

    def test_validate_arguments_uses_configurable_vuln_id(self, tmp_path):
        """validate_arguments checks for the configured vuln_id, not hardcoded 'vuln_0'."""
        (tmp_path / "metadata.json").write_text("{}")
        # Only create vuln_1, not vuln_0
        vuln_dir = tmp_path / "synthetic_vulnerabilities" / "vuln_1"
        verify_dir = vuln_dir / "verify_files"
        verify_dir.mkdir(parents=True)
        (vuln_dir / "vulnerability.patch").write_text("patch content")

        config = build_exploit_runner_config()
        workflow = ExploitWorkflow(
            config=config,
            app_name="test_app",
            app_dir=tmp_path,
            vuln_id="vuln_1",
        )

        # Mock get_app_metadata since it uses hardcoded project paths
        with patch("utils.utils.get_app_metadata", return_value={}):
            # Should pass validation since vuln_1 exists
            workflow.validate_arguments()

    def test_validate_arguments_fails_when_vuln_id_dir_missing(self, tmp_path):
        """validate_arguments fails if the specified vuln_id directory doesn't exist."""
        (tmp_path / "metadata.json").write_text("{}")
        # Create vuln_0, but workflow is configured for vuln_1
        vuln_dir = tmp_path / "synthetic_vulnerabilities" / "vuln_0"
        verify_dir = vuln_dir / "verify_files"
        verify_dir.mkdir(parents=True)
        (vuln_dir / "vulnerability.patch").write_text("patch content")

        config = build_exploit_runner_config()
        workflow = ExploitWorkflow(
            config=config,
            app_name="test_app",
            app_dir=tmp_path,
            vuln_id="vuln_1",  # This doesn't exist
        )
        with pytest.raises(
            ValueError, match="Vulnerability directory not found.*vuln_1"
        ):
            workflow.validate_arguments()


class TestDiscoveryWorkflowFlagGeneration:
    """Tests for flag generation in DiscoveryWorkflow."""

    def test_discovery_workflow_generates_flags_on_setup(self, tmp_path):
        """setup_runtime_environment generates fresh flags before install."""
        # Create app structure
        app_dir = tmp_path / "apps" / "test_app"
        app_dir.mkdir(parents=True)
        (app_dir / "metadata.json").write_text(
            '{"container_names": ["redis", "postgres"]}'
        )

        config = build_runner_config()
        workflow = DiscoveryWorkflow(
            config=config,
            app_name="test_app",
            app_dir=app_dir,
            project_root=tmp_path,
        )
        workflow.metadata = {"container_names": ["redis", "postgres"]}

        # Mock the heavy dependencies (must mock at source module for lazy imports)
        with patch(
            "utils.uuid_flags_utils.generate_and_save_flags"
        ) as mock_generate, patch("utils.emulator_manager.EmulatorManager"), patch(
            "utils.apk_utils.setup_apk"
        ), patch(
            "utils.setup_utils.install_app_and_setup_backend"
        ), patch(
            "agent.agent_container.setup_agent_environment"
        ):
            workflow.setup_runtime_environment()

            # Verify flags were generated with container names
            mock_generate.assert_called_once_with(str(tmp_path), ["redis", "postgres"])

    def test_discovery_workflow_generates_flags_with_empty_containers(self, tmp_path):
        """setup_runtime_environment generates flags even without containers."""
        app_dir = tmp_path / "apps" / "test_app"
        app_dir.mkdir(parents=True)
        (app_dir / "metadata.json").write_text("{}")

        config = build_runner_config()
        workflow = DiscoveryWorkflow(
            config=config,
            app_name="test_app",
            app_dir=app_dir,
            project_root=tmp_path,
        )
        workflow.metadata = {}

        with patch(
            "utils.uuid_flags_utils.generate_and_save_flags"
        ) as mock_generate, patch("utils.emulator_manager.EmulatorManager"), patch(
            "utils.apk_utils.setup_apk"
        ), patch(
            "utils.setup_utils.install_app_and_setup_backend"
        ), patch(
            "agent.agent_container.setup_agent_environment"
        ):
            workflow.setup_runtime_environment()

            # Verify flags were generated with empty container list
            mock_generate.assert_called_once_with(str(tmp_path), [])
