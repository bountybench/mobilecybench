"""Tests for Workflow._restart_runtime() and _run_exploit() helpers."""

import json
import subprocess
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
        max_iterations=10,
        max_model_response_tokens=1000,
        dry_run=False,
        emulator_backend="native",
        emulator_display="headed",
        network_mode="restricted",
        synthetic_vuln_id="vuln_0",
    )
    wf = _ConcreteWorkflow(config, "testapp", tmp_path)
    wf.emulator = MagicMock()
    return wf


def test_save_result_preserves_existing_file_when_json_write_fails(workflow):
    workflow.app_dir.mkdir(parents=True)
    scores_file = workflow.app_dir / workflow.SCORE_FILE
    original = {"status": "previous", "score": 1}
    scores_file.write_text(json.dumps(original), encoding="utf-8")

    with pytest.raises(TypeError):
        workflow._save_result({"status": "broken", "score": 0, "bad": object()})

    assert json.loads(scores_file.read_text(encoding="utf-8")) == original
    assert not (workflow.app_dir / f"{workflow.SCORE_FILE}.tmp").exists()


def test_save_artifacts_captures_agent_outputs_and_firewall_logs(workflow, tmp_path):
    workflow.agent_env = MagicMock()

    with patch("agent.firewall.save_logs") as mock_save_logs:
        workflow.save_artifacts(tmp_path)

    workflow.agent_env.save_agent_exploit.assert_called_once_with(tmp_path)
    workflow.agent_env.save_agent_output.assert_called_once_with(tmp_path)
    mock_save_logs.assert_called_once_with(tmp_path)


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
    def test_rejects_missing_replay_resource(self, workflow, tmp_path):
        with pytest.raises(ValueError, match="exactly one"):
            workflow._run_exploit(
                exploit_dir=tmp_path / "agent_exploit",
                output_dir=tmp_path / "replay_output",
                exploit_runner=tmp_path / "run_exploit.sh",
                exploit_image="test:latest",
                codebase_dir=None,
                replay_apk=None,
            )

    def test_rejects_multiple_replay_resources(self, workflow, tmp_path):
        with pytest.raises(ValueError, match="exactly one"):
            workflow._run_exploit(
                exploit_dir=tmp_path / "agent_exploit",
                output_dir=tmp_path / "replay_output",
                exploit_runner=tmp_path / "run_exploit.sh",
                exploit_image="test:latest",
                codebase_dir=tmp_path / "codebase",
                replay_apk=tmp_path / "app.apk",
            )

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
            replay_apk=None,
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
            replay_apk=None,
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
            replay_apk=None,
        )
        assert result["replay_exit_code"] == 42

    def test_wipe_output_dir_true_clears_preexisting_files(self, workflow, tmp_path):
        """Default behavior: synthetic exploit reuses one output_dir across
        vuln+clean phases and relies on the wipe for phase-isolation."""
        exploit_dir = tmp_path / "agent_exploit"
        exploit_dir.mkdir()
        (exploit_dir / "exploit.sh").write_text("exit 0")

        output_dir = tmp_path / "replay_output"
        output_dir.mkdir()
        stale = output_dir / "stale_from_previous_phase"
        stale.write_text("phase1 artifact")

        exploit_runner = tmp_path / "run_exploit.sh"
        exploit_runner.write_text("#!/bin/bash\nexit 0")

        workflow._run_exploit(
            exploit_dir=exploit_dir,
            output_dir=output_dir,
            exploit_runner=exploit_runner,
            exploit_image="test:latest",
            codebase_dir=tmp_path,
            replay_apk=None,
        )
        assert not stale.exists(), "default wipe should clear stale phase artifacts"

    def test_wipe_output_dir_false_preserves_prepare_app_seed(self, workflow, tmp_path):
        """RemoteAttacker path: prepare_app already seeded ``output_dir`` as
        ``MCB_OUTPUT_DIR``; ``_run_exploit`` must not wipe it before the
        verifier reads it. Matches the validator's per-phase contract
        (scripts/task_runtime_common.sh) where prepare_app/exploit/verifier
        share one ``$TASK_RUNTIME_OUTPUT_DIR``."""
        exploit_dir = tmp_path / "agent_exploit"
        exploit_dir.mkdir()
        (exploit_dir / "exploit.sh").write_text("exit 0")

        output_dir = tmp_path / "replay_output"
        output_dir.mkdir()
        seed = output_dir / "prepare_app_seed"
        seed.write_text("seeded-by-prepare_app")

        exploit_runner = tmp_path / "run_exploit.sh"
        exploit_runner.write_text("#!/bin/bash\nexit 0")

        workflow._run_exploit(
            exploit_dir=exploit_dir,
            output_dir=output_dir,
            exploit_runner=exploit_runner,
            exploit_image="test:latest",
            codebase_dir=tmp_path,
            replay_apk=None,
            wipe_output_dir=False,
        )
        assert seed.read_text() == "seeded-by-prepare_app"
        assert (
            output_dir / "stdout.txt"
        ).exists(), "exploit stdout should still land alongside the prepare_app seed"


class TestRunExploitContainerScript:
    def _base_args(self, tmp_path):
        exploit_dir = tmp_path / "agent_exploit"
        exploit_dir.mkdir()
        (exploit_dir / "exploit.sh").write_text("#!/bin/bash\nexit 0\n")
        return [
            "bash",
            str(
                Path(__file__).resolve().parents[2]
                / "utils"
                / "run_exploit_container.sh"
            ),
            "--exploit-dir",
            str(exploit_dir),
            "--output-dir",
            str(tmp_path / "replay_output"),
        ]

    def test_rejects_missing_replay_resource(self, tmp_path):
        proc = subprocess.run(
            self._base_args(tmp_path), capture_output=True, text=True, check=False
        )
        assert proc.returncode == 1
        assert "exactly one of --codebase-dir or --apk-dir" in proc.stderr

    def test_help_documents_unique_adb_proxy_name(self, tmp_path):
        proc = subprocess.run(
            self._base_args(tmp_path) + ["--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0
        assert "--adb-proxy-name <n>" in proc.stdout
        assert "adb-proxy-exploit-$$" in proc.stdout

    def test_rejects_empty_adb_proxy_name(self, tmp_path):
        proc = subprocess.run(
            self._base_args(tmp_path) + ["--adb-proxy-name", ""],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 1
        assert "--adb-proxy-name must not be empty" in proc.stderr

    def test_rejects_multiple_replay_resources(self, tmp_path):
        codebase_dir = tmp_path / "codebase"
        apk_dir = tmp_path / "apk"
        codebase_dir.mkdir()
        apk_dir.mkdir()
        proc = subprocess.run(
            self._base_args(tmp_path)
            + ["--codebase-dir", str(codebase_dir), "--apk-dir", str(apk_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 1
        assert "exactly one of --codebase-dir or --apk-dir" in proc.stderr
