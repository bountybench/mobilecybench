"""Tests for Workflow base class and implementations."""

from unittest.mock import patch

import pytest

from models.config import RunnerConfig
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

    def test_validate_arguments_fails_wrong_build_type(self, tmp_path):
        """validate_arguments raises error if build_type is not 'source' or 'skip-apk'."""
        app_dir = tmp_path / "apps" / "test_app"
        app_dir.mkdir(parents=True)
        (app_dir / "metadata.json").write_text("{}")
        vuln_dir = app_dir / "synthetic_vulnerabilities" / "vuln_0"
        (vuln_dir / "verify_files").mkdir(parents=True)
        (vuln_dir / "vulnerability.patch").write_text("patch content")
        workflow = ExploitWorkflow(
            _config(workflow="exploit", build_type="download-apk"), "test_app", tmp_path
        )
        with pytest.raises(
            ValueError, match="requires build_type='source' or 'skip-apk'"
        ):
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
            mock_generate.assert_called_once_with(str(tmp_path), ["redis", "postgres"])

    def test_discovery_workflow_generates_flags_with_empty_containers(self, tmp_path):
        """setup_runtime_environment generates flags even without containers."""
        (tmp_path / "apps" / "test_app").mkdir(parents=True)
        workflow = DiscoveryWorkflow(_config(), "test_app", tmp_path)
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
            mock_generate.assert_called_once_with(str(tmp_path), [])
