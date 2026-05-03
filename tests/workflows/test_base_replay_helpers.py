"""Tests for Workflow._restart_runtime() and _run_exploit() helpers."""

import logging
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from models.config import RunnerConfig
from workflows.base import Workflow

REPO_ROOT = Path(__file__).resolve().parents[2]


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


def _write_run_checks(probe_dir: Path, body: str) -> Path:
    probe_dir.mkdir(parents=True, exist_ok=True)
    run_checks = probe_dir / "run_checks.sh"
    run_checks.write_text(f"#!/bin/bash\n{body}", encoding="utf-8")
    return run_checks


def _write_probe_scripts(probe_dir: Path) -> None:
    probe_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "test_access_control.py",
        "test_availability.py",
        "test_confidentiality.py",
        "test_integrity.py",
    ):
        (probe_dir / name).write_text(
            'import json\nprint(json.dumps({"score": 1}))\n',
            encoding="utf-8",
        )
    (probe_dir / "metadata.json").write_text("{}", encoding="utf-8")
    (probe_dir / "generic_probe_config.json").write_text(
        '{"generic_probe_applicability": {}}',
        encoding="utf-8",
    )


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

    def test_hung_exploit_times_out_and_writes_artifact(self, workflow, tmp_path):
        workflow.config.script_timeout = 0.2
        exploit_dir = tmp_path / "agent_exploit"
        exploit_dir.mkdir()
        (exploit_dir / "exploit.sh").write_text("sleep forever")

        output_dir = tmp_path / "replay_output"
        exploit_runner = tmp_path / "run_exploit.sh"
        exploit_runner.write_text("#!/bin/bash\nprintf 'partial output'; sleep 10\n")

        started = time.monotonic()
        result = workflow._run_exploit(
            exploit_dir=exploit_dir,
            output_dir=output_dir,
            exploit_runner=exploit_runner,
            exploit_image="test:latest",
            codebase_dir=tmp_path,
        )

        assert time.monotonic() - started < 5
        assert result["replay_exit_code"] == Workflow.TIMEOUT_EXIT_CODE
        assert result["replay_timed_out"] is True
        stdout = (output_dir / "stdout.txt").read_text(encoding="utf-8")
        assert "timed out" in stdout
        assert "timed out" in Path(result["replay_evidence_path"]).read_text(
            encoding="utf-8"
        )


class TestRunChecks:
    def test_hung_probe_times_out(self, workflow, tmp_path, caplog):
        workflow.config.script_timeout = 0.2
        probe_dir = tmp_path / "probe"
        _write_run_checks(probe_dir, "printf 'probe started'; sleep 10\n")

        with caplog.at_level(logging.ERROR, logger="workflows.base"):
            started = time.monotonic()
            ok = workflow._run_checks(
                "",
                app_scores_out=tmp_path / "app_scores.json",
                generic_scores_out=tmp_path / "generic_scores.json",
                probe_dir=probe_dir,
            )

        assert time.monotonic() - started < 5
        assert ok is False
        assert "run_checks.sh timed out" in caplog.text

    def test_project_root_run_checks_fallback_honors_score_env_paths(
        self, workflow, tmp_path
    ):
        workflow.project_root = REPO_ROOT
        probe_dir = tmp_path / "probe"
        _write_probe_scripts(probe_dir)

        app_scores = tmp_path / "app_scores.json"
        generic_scores = tmp_path / "generic_scores.json"

        ok = workflow._run_checks(
            "",
            app_scores_out=app_scores,
            generic_scores_out=generic_scores,
            probe_dir=probe_dir,
        )

        assert ok is True
        assert app_scores.exists()
        assert generic_scores.exists()

    def test_project_root_fallback_missing_score_file_fails_closed(
        self, workflow, tmp_path, caplog
    ):
        probe_dir = tmp_path / "probe"
        probe_dir.mkdir()
        (tmp_path / "run_checks.sh").write_text(
            "#!/bin/bash\n" "printf '%s\\n' '{\"scores\": {}}' > \"$APP_SCORES_OUT\"\n",
            encoding="utf-8",
        )

        with caplog.at_level(logging.ERROR, logger="workflows.base"):
            ok = workflow._run_checks(
                "",
                app_scores_out=tmp_path / "app_scores.json",
                generic_scores_out=tmp_path / "generic_scores.json",
                probe_dir=probe_dir,
            )

        assert ok is False
        assert "Score output file not produced" in caplog.text

    def test_probe_local_missing_score_file_is_legacy_warning(
        self, workflow, tmp_path, caplog
    ):
        probe_dir = tmp_path / "probe"
        _write_run_checks(
            probe_dir,
            "printf '%s\\n' '{\"scores\": {}}' > \"$APP_SCORES_OUT\"\n",
        )

        with caplog.at_level(logging.WARNING, logger="workflows.base"):
            ok = workflow._run_checks(
                "",
                app_scores_out=tmp_path / "app_scores.json",
                generic_scores_out=tmp_path / "generic_scores.json",
                probe_dir=probe_dir,
            )

        assert ok is True
        assert "Score output file not produced" in caplog.text

    def test_project_root_fallback_malformed_score_json_fails_closed(
        self, workflow, tmp_path, caplog
    ):
        probe_dir = tmp_path / "probe"
        probe_dir.mkdir()
        (tmp_path / "run_checks.sh").write_text(
            "#!/bin/bash\n"
            "printf '%s\\n' '{\"scores\": {}}' > \"$APP_SCORES_OUT\"\n"
            "printf '%s\\n' '{not-json' > \"$GENERIC_SCORES_OUT\"\n",
            encoding="utf-8",
        )

        with caplog.at_level(logging.ERROR, logger="workflows.base"):
            ok = workflow._run_checks(
                "",
                app_scores_out=tmp_path / "app_scores.json",
                generic_scores_out=tmp_path / "generic_scores.json",
                probe_dir=probe_dir,
            )

        assert ok is False
        assert "Invalid JSON" in caplog.text
