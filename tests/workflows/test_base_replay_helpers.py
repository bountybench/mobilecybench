"""Tests for Workflow._restart_runtime() and _run_exploit() helpers."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from models.config import RunnerConfig
from workflows.base import Workflow


class _ConcreteWorkflow(Workflow):
    """Minimal concrete subclass for testing base helpers."""

    def validate_arguments(self):
        pass

    def setup_runtime_environment(self):
        pass

    def evaluate(self):
        return {}

    def _build_apks_from_source(self):
        pass


@pytest.fixture
def workflow(tmp_path):
    config = RunnerConfig(
        build_type="skip-apk",
        model="test",
        agent_image="test:latest",
        server_access=True,
        adb_access="full",
        max_iterations=10,
        max_model_response_tokens=1000,
        screenshot_mode=False,
        dry_run=False,
        emulator_backend="native",
        emulator_display="headed",
        synthetic_vuln_id="vuln_0",
    )
    wf = _ConcreteWorkflow(config, "testapp", tmp_path)
    wf.emulator = MagicMock()
    return wf


class TestRestartRuntime:
    @patch("utils.setup_utils.install_app_and_setup_backend")
    @patch("utils.emulator_certs.inject_system_ca")
    def test_forwards_inject_flags_and_start_ssrf(
        self, mock_ca, mock_install, workflow
    ):
        apk_path = Path("apk/testapp.apk")
        workflow._restart_runtime(apk_path, inject_flags=True, start_ssrf=True)
        mock_install.assert_called_once()
        _, kwargs = mock_install.call_args
        assert kwargs["inject_flags"] is True
        assert kwargs["start_ssrf"] is True

    @patch("utils.setup_utils.install_app_and_setup_backend")
    @patch("utils.emulator_certs.inject_system_ca")
    def test_defaults_preserve_existing_behavior(self, mock_ca, mock_install, workflow):
        apk_path = Path("apk/testapp.apk")
        workflow._restart_runtime(apk_path)
        _, kwargs = mock_install.call_args
        assert kwargs["inject_flags"] is False
        assert kwargs["start_ssrf"] is False


class TestRunExploit:
    def test_writes_evidence_files(self, workflow, tmp_path):
        exploit_dir = tmp_path / "agent_exploit"
        exploit_dir.mkdir()
        (exploit_dir / "exploit.sh").write_text("echo hello")

        output_dir = tmp_path / "replay_output"
        exploit_runner = tmp_path / "run_exploit.sh"
        # Script that echoes stdout and stderr
        exploit_runner.write_text(
            '#!/bin/bash\necho "STDOUT_LINE"\necho "STDERR_LINE" >&2\nexit 0'
        )

        result = workflow._run_exploit(
            exploit_dir=exploit_dir,
            output_dir=output_dir,
            exploit_runner=exploit_runner,
            exploit_image="test:latest",
            codebase_dir=tmp_path,
        )

        # Check files were written
        assert (output_dir / "stdout.txt").exists()
        assert (output_dir / "replay_evidence.log").exists()

        # Check evidence content
        evidence = (output_dir / "replay_evidence.log").read_text()
        assert "stdout" in evidence.lower() or "STDOUT_LINE" in evidence
        assert "stderr" in evidence.lower() or "STDERR_LINE" in evidence

        # Check replay_evidence_path in result
        assert "replay_evidence_path" in result
        assert Path(result["replay_evidence_path"]).exists()

    def test_evidence_includes_agent_output_text_files(self, workflow, tmp_path):
        exploit_dir = tmp_path / "agent_exploit"
        exploit_dir.mkdir()
        (exploit_dir / "exploit.sh").write_text("echo hello")

        output_dir = tmp_path / "replay_output"

        # The exploit runner script creates agent_output with a text file
        exploit_runner = tmp_path / "run_exploit.sh"
        exploit_runner.write_text(
            "#!/bin/bash\n"
            f'mkdir -p "{output_dir}/agent_output"\n'
            f'echo "SECRET_DATA" > "{output_dir}/agent_output/captured.txt"\n'
            "exit 0\n"
        )

        result = workflow._run_exploit(
            exploit_dir=exploit_dir,
            output_dir=output_dir,
            exploit_runner=exploit_runner,
            exploit_image="test:latest",
            codebase_dir=tmp_path,
        )

        evidence = Path(result["replay_evidence_path"]).read_text()
        assert "SECRET_DATA" in evidence

    def test_exit_code_preserved(self, workflow, tmp_path):
        exploit_dir = tmp_path / "agent_exploit"
        exploit_dir.mkdir()
        (exploit_dir / "exploit.sh").write_text("exit 42")

        output_dir = tmp_path / "replay_output"
        exploit_runner = tmp_path / "run_exploit.sh"
        exploit_runner.write_text("#!/bin/bash\nexit 42")

        result = workflow._run_exploit(
            exploit_dir=exploit_dir,
            output_dir=output_dir,
            exploit_runner=exploit_runner,
            exploit_image="test:latest",
            codebase_dir=tmp_path,
        )
        assert result["replay_exit_code"] == 42
