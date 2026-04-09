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


class TestBuildEvidenceLog:
    def test_includes_replay_stdout(self, tmp_path):
        evidence_path = tmp_path / "evidence.log"
        Workflow.build_evidence_log(evidence_path, replay_stdout="EXPLOIT OUTPUT")
        content = evidence_path.read_text()
        assert "EXPLOIT OUTPUT" in content

    def test_includes_agent_output_files(self, tmp_path):
        agent_output = tmp_path / "agent_output"
        agent_output.mkdir()
        (agent_output / "result.txt").write_text("CAPTURED_SECRET")
        evidence_path = tmp_path / "evidence.log"
        Workflow.build_evidence_log(evidence_path, agent_output_dir=agent_output)
        assert "CAPTURED_SECRET" in evidence_path.read_text()

    def test_includes_agent_exploit_files(self, tmp_path):
        agent_exploit = tmp_path / "agent_exploit"
        agent_exploit.mkdir()
        (agent_exploit / "exploit.sh").write_text("curl http://evil")
        evidence_path = tmp_path / "evidence.log"
        Workflow.build_evidence_log(evidence_path, agent_exploit_dir=agent_exploit)
        assert "curl http://evil" in evidence_path.read_text()

    def test_includes_agent_log(self, tmp_path):
        agent_log = tmp_path / "agent.log"
        agent_log.write_text("Found password: admin123")
        evidence_path = tmp_path / "evidence.log"
        Workflow.build_evidence_log(evidence_path, agent_log=agent_log)
        content = evidence_path.read_text()
        assert "Found password: admin123" in content
        assert "agent.log" in content

    def test_skips_missing_sources(self, tmp_path):
        evidence_path = tmp_path / "evidence.log"
        Workflow.build_evidence_log(
            evidence_path,
            agent_output_dir=tmp_path / "nonexistent",
            agent_exploit_dir=tmp_path / "also_missing",
            agent_log=tmp_path / "no_such.log",
        )
        assert evidence_path.read_text() == ""

    def test_excludes_binary_files(self, tmp_path):
        agent_output = tmp_path / "agent_output"
        agent_output.mkdir()
        (agent_output / "binary.bin").write_bytes(b"\x00\x01\x80\xff")
        (agent_output / "text.txt").write_text("readable")
        evidence_path = tmp_path / "evidence.log"
        Workflow.build_evidence_log(evidence_path, agent_output_dir=agent_output)
        content = evidence_path.read_text()
        assert "readable" in content
        assert "binary.bin" not in content


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

    def test_evidence_includes_agent_log_and_exploit_source(self, workflow, tmp_path):
        exploit_dir = tmp_path / "agent_exploit"
        exploit_dir.mkdir()
        (exploit_dir / "exploit.sh").write_text("echo hello")

        # Simulate logs_dir with agent.log and agent_exploit/
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        (logs_dir / "agent.log").write_text("Agent found credential: secret123")
        agent_exploit_in_logs = logs_dir / "agent_exploit"
        agent_exploit_in_logs.mkdir()
        (agent_exploit_in_logs / "exploit.sh").write_text("curl http://evil.com")

        output_dir = tmp_path / "replay_output"
        exploit_runner = tmp_path / "run_exploit.sh"
        exploit_runner.write_text('#!/bin/bash\necho "REPLAY"\nexit 0')

        result = workflow._run_exploit(
            exploit_dir=exploit_dir,
            output_dir=output_dir,
            exploit_runner=exploit_runner,
            exploit_image="test:latest",
            codebase_dir=tmp_path,
            logs_dir=logs_dir,
        )

        evidence = Path(result["replay_evidence_path"]).read_text()
        assert "Agent found credential: secret123" in evidence
        assert "curl http://evil.com" in evidence
        assert "REPLAY" in evidence

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
