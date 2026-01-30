"""Tests for Workflow base class and implementations."""

import pytest

from workflows.base import Workflow
from workflows.discovery import DiscoveryWorkflow
from workflows.exploit import ExploitWorkflow

# Common agent config params used across all workflow tests
AGENT_CONFIG = {
    "max_model_response_tokens": 1000,
    "max_kali_message_tokens": 1000,
    "max_context_length": 10000,
}


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
        workflow = DiscoveryWorkflow(
            app_name="test_app",
            app_dir=tmp_path,
            model="gpt-4",
            max_iterations=10,
            **AGENT_CONFIG,
        )
        assert workflow.app_name == "test_app"
        assert workflow.model == "gpt-4"
        assert workflow.max_iterations == 10
        assert workflow.build_type == "source"  # default
        assert workflow.dry_run is False  # default

    def test_discovery_workflow_accepts_all_parameters(self, tmp_path):
        """DiscoveryWorkflow accepts all optional parameters."""
        workflow = DiscoveryWorkflow(
            app_name="test_app",
            app_dir=tmp_path,
            model="gpt-4",
            max_iterations=10,
            **AGENT_CONFIG,
            screenshot_mode=True,
            build_type="download-apk",
            agent_image="custom-image:latest",
            project_root=tmp_path,
            dry_run=True,
        )
        assert workflow.build_type == "download-apk"
        assert workflow.agent_image == "custom-image:latest"
        assert workflow.project_root == tmp_path
        assert workflow.dry_run is True
        assert workflow.screenshot_mode is True

    def test_validate_arguments_fails_missing_app_dir(self, tmp_path):
        """validate_arguments raises error if app_dir doesn't exist."""
        non_existent = tmp_path / "does_not_exist"
        workflow = DiscoveryWorkflow(
            app_name="test_app",
            app_dir=non_existent,
            model="gpt-4",
            max_iterations=10,
            **AGENT_CONFIG,
        )
        with pytest.raises(ValueError, match="App directory not found"):
            workflow.validate_arguments()

    def test_validate_arguments_fails_missing_metadata(self, tmp_path):
        """validate_arguments raises error if metadata.json doesn't exist."""
        workflow = DiscoveryWorkflow(
            app_name="test_app",
            app_dir=tmp_path,
            model="gpt-4",
            max_iterations=10,
            **AGENT_CONFIG,
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
        workflow = ExploitWorkflow(
            app_name="test_app",
            app_dir=tmp_path,
            model="gpt-4",
            max_iterations=10,
            **AGENT_CONFIG,
        )
        assert workflow.app_name == "test_app"
        assert workflow.model == "gpt-4"
        assert workflow.build_type == "source"  # default
        assert workflow.dry_run is False  # default

    def test_validate_arguments_fails_missing_app_dir(self, tmp_path):
        """validate_arguments raises error if app_dir doesn't exist."""
        non_existent = tmp_path / "does_not_exist"
        workflow = ExploitWorkflow(
            app_name="test_app",
            app_dir=non_existent,
            model="gpt-4",
            max_iterations=10,
            **AGENT_CONFIG,
        )
        with pytest.raises(ValueError, match="App directory not found"):
            workflow.validate_arguments()

    def test_validate_arguments_fails_missing_vuln_dir(self, tmp_path):
        """validate_arguments raises error if target vulnerability dir doesn't exist."""
        (tmp_path / "metadata.json").write_text("{}")
        workflow = ExploitWorkflow(
            app_name="test_app",
            app_dir=tmp_path,
            model="gpt-4",
            max_iterations=10,
            **AGENT_CONFIG,
        )
        with pytest.raises(ValueError, match="Vulnerability directory not found"):
            workflow.validate_arguments()

    def test_validate_arguments_fails_missing_verify_files(self, tmp_path):
        """validate_arguments raises error if verify_files doesn't exist."""
        (tmp_path / "metadata.json").write_text("{}")
        vuln_dir = tmp_path / "synthetic_vulnerabilities" / "vuln_0"
        vuln_dir.mkdir(parents=True)

        workflow = ExploitWorkflow(
            app_name="test_app",
            app_dir=tmp_path,
            model="gpt-4",
            max_iterations=10,
            **AGENT_CONFIG,
        )
        with pytest.raises(ValueError, match="verify_files not found"):
            workflow.validate_arguments()

    def test_validate_arguments_fails_missing_patch(self, tmp_path):
        """validate_arguments raises error if vulnerability.patch doesn't exist."""
        (tmp_path / "metadata.json").write_text("{}")
        verify_dir = tmp_path / "synthetic_vulnerabilities" / "vuln_0" / "verify_files"
        verify_dir.mkdir(parents=True)

        workflow = ExploitWorkflow(
            app_name="test_app",
            app_dir=tmp_path,
            model="gpt-4",
            max_iterations=10,
            **AGENT_CONFIG,
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

        workflow = ExploitWorkflow(
            app_name="test_app",
            app_dir=tmp_path,
            model="gpt-4",
            max_iterations=10,
            **AGENT_CONFIG,
            build_type="download-apk",  # Invalid for synthetic mode
        )
        with pytest.raises(ValueError, match="requires build_type='source'"):
            workflow.validate_arguments()
