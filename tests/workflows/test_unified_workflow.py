"""Tests for UnifiedWorkflow validate/setup/evaluate."""

import json
from unittest.mock import MagicMock, patch

import pytest

from models.config import RunnerConfig
from workflows.unified import UnifiedWorkflow


@pytest.fixture
def unified_config():
    return RunnerConfig(
        build_type="skip-apk",
        model="test",
        agent_image="test:latest",
        agent_mode="custom",
        max_iterations=10,
        max_model_response_tokens=1000,
        screenshot_mode=False,
        dry_run=False,
        gold_run=False,
        emulator_backend="native",
        emulator_display="headed",
        workflow="unified",
        synthetic_vuln_id="vuln_0",
        reasoning_effort=None,
        script_timeout=600,
        build_command_timeout=1200,
        emulator_boot_timeout_seconds=300,
        agent_timeout=1800,
    )


def _setup_app_dir(
    tmp_path, *, with_security_patch=True, with_hidden_config=True, with_probes=True
):
    """Create a minimal app directory structure for testing."""
    app_dir = tmp_path / "apps" / "testapp"
    app_dir.mkdir(parents=True)

    metadata = {
        "commit_version": "abc123",
        "sdk": "34",
        "package_name": "com.test.app",
        "container_names": [],
        "app_server": "",
    }
    (app_dir / "metadata.json").write_text(json.dumps(metadata))

    if with_security_patch:
        (app_dir / "security.patch").write_text("--- a/file\n+++ b/file\n")

    if with_hidden_config:
        config = {
            "version": 1,
            "generic_probe_applicability": {
                "access.ssrf_detected": False,
                "confidentiality.secrets": True,
                "confidentiality.app_flag": True,
                "confidentiality.container_flag": False,
                "integrity.app_flag": True,
                "integrity.app_pwned_file": True,
                "integrity.container_flag": False,
                "integrity.container_pwned_file": False,
                "availability.check_container_health": False,
            },
        }
        (app_dir / "hidden_eval_config.json").write_text(json.dumps(config))

    if with_probes:
        for f in [
            "test_access_control.py",
            "test_availability.py",
            "test_confidentiality.py",
            "test_integrity.py",
        ]:
            (app_dir / f).write_text("# probe")

    return app_dir


class TestValidateArguments:
    def test_valid_app_passes(self, unified_config, tmp_path):
        _setup_app_dir(tmp_path)
        wf = UnifiedWorkflow(unified_config, "testapp", tmp_path)
        wf.validate_arguments()
        assert wf.metadata["package_name"] == "com.test.app"

    def test_missing_app_dir_fails(self, unified_config, tmp_path):
        wf = UnifiedWorkflow(unified_config, "missing_app", tmp_path)
        with pytest.raises(ValueError, match="App directory not found"):
            wf.validate_arguments()

    def test_missing_security_patch_fails(self, unified_config, tmp_path):
        _setup_app_dir(tmp_path, with_security_patch=False)
        wf = UnifiedWorkflow(unified_config, "testapp", tmp_path)
        with pytest.raises(ValueError, match="security.patch"):
            wf.validate_arguments()

    def test_missing_hidden_eval_config_fails(self, unified_config, tmp_path):
        _setup_app_dir(tmp_path, with_hidden_config=False)
        wf = UnifiedWorkflow(unified_config, "testapp", tmp_path)
        with pytest.raises(FileNotFoundError, match="hidden_eval_config"):
            wf.validate_arguments()

    def test_missing_probe_files_fails(self, unified_config, tmp_path):
        _setup_app_dir(tmp_path, with_probes=False)
        wf = UnifiedWorkflow(unified_config, "testapp", tmp_path)
        with pytest.raises(ValueError, match="test_access_control.py"):
            wf.validate_arguments()


class TestSetupRuntimeEnvironment:
    @patch("utils.setup_utils.check_connectivity")
    @patch("agent.agent_container.setup_agent_environment")
    @patch("utils.setup_utils.install_app_and_setup_backend")
    @patch("utils.emulator_certs.inject_system_ca")
    @patch("utils.emulator_manager.EmulatorManager")
    def test_setup_does_not_inject_flags(
        self,
        MockEmu,
        mock_ca,
        mock_install,
        mock_agent_env,
        mock_conn,
        unified_config,
        tmp_path,
    ):
        app_dir = _setup_app_dir(tmp_path)
        # Create APK files
        (app_dir / "apk").mkdir()
        (app_dir / "apk" / "testapp.apk").write_bytes(b"APK")
        (app_dir / "apk" / "hardened").mkdir()
        (app_dir / "apk" / "hardened" / "testapp.apk").write_bytes(b"APK")

        mock_emu_instance = MagicMock()
        MockEmu.return_value = mock_emu_instance
        mock_agent_env.return_value = MagicMock()

        wf = UnifiedWorkflow(unified_config, "testapp", tmp_path)
        wf.metadata = json.loads((app_dir / "metadata.json").read_text())
        wf.setup_runtime_environment()

        # Verify no flag injection
        _, kwargs = mock_install.call_args
        assert kwargs.get("inject_flags") is False

    @patch("utils.setup_utils.check_connectivity")
    @patch("agent.agent_container.setup_agent_environment")
    @patch("utils.setup_utils.install_app_and_setup_backend")
    @patch("utils.emulator_certs.inject_system_ca")
    @patch("utils.emulator_manager.EmulatorManager")
    def test_setup_uses_unified_workflow_label(
        self,
        MockEmu,
        mock_ca,
        mock_install,
        mock_agent_env,
        mock_conn,
        unified_config,
        tmp_path,
    ):
        app_dir = _setup_app_dir(tmp_path)
        (app_dir / "apk").mkdir()
        (app_dir / "apk" / "testapp.apk").write_bytes(b"APK")
        (app_dir / "apk" / "hardened").mkdir()
        (app_dir / "apk" / "hardened" / "testapp.apk").write_bytes(b"APK")

        MockEmu.return_value = MagicMock()
        mock_agent_env.return_value = MagicMock()

        wf = UnifiedWorkflow(unified_config, "testapp", tmp_path)
        wf.metadata = json.loads((app_dir / "metadata.json").read_text())
        wf.setup_runtime_environment()

        _, kwargs = mock_agent_env.call_args
        assert kwargs["workflow"] == "unified"
