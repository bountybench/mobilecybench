"""Tests for malicious APK replay — evidence assembly and exit code parsing."""

from unittest.mock import patch

from evaluation.replay_apk import (
    EvidenceBundle,
    assemble_evidence_log,
    run_instrument,
)


class TestAssembleEvidenceLog:
    """Evidence log combines instrument stdout + logcat + apk files."""

    def test_combines_all_sources(self, tmp_path):
        # Create apk_evidence dir with a file
        evidence_dir = tmp_path / "apk_evidence"
        evidence_dir.mkdir()
        (evidence_dir / "stolen_creds.json").write_text('{"password": "s3cret"}')

        evidence = EvidenceBundle(
            instrument_stdout="INSTRUMENTATION_CODE: 0\nINSTRUMENTATION_RESULT: token=abc",
            logcat="I/MOBILECYBENCH: Exploit result: SUCCESS",
            evidence_dir=evidence_dir,
        )

        log_path = assemble_evidence_log(evidence, tmp_path)

        content = log_path.read_text()
        assert "INSTRUMENTATION_CODE: 0" in content
        assert "Exploit result: SUCCESS" in content
        assert '"password": "s3cret"' in content
        assert "apk_evidence/stolen_creds.json" in content

    def test_handles_no_apk_files(self, tmp_path):
        evidence = EvidenceBundle(
            instrument_stdout="INSTRUMENTATION_CODE: 1",
            logcat="I/MOBILECYBENCH: Exploit result: FAILURE",
            evidence_dir=None,
        )

        log_path = assemble_evidence_log(evidence, tmp_path)

        content = log_path.read_text()
        assert "INSTRUMENTATION_CODE: 1" in content
        assert "apk_evidence" not in content

    def test_skips_binary_files(self, tmp_path):
        evidence_dir = tmp_path / "apk_evidence"
        evidence_dir.mkdir()
        (evidence_dir / "text.txt").write_text("readable")
        (evidence_dir / "binary.bin").write_bytes(b"\x00\x01\xff\xfe")

        evidence = EvidenceBundle(
            instrument_stdout="",
            logcat="",
            evidence_dir=evidence_dir,
        )

        log_path = assemble_evidence_log(evidence, tmp_path)

        content = log_path.read_text()
        assert "readable" in content
        assert "binary.bin" not in content

    def test_handles_empty_evidence(self, tmp_path):
        evidence = EvidenceBundle(instrument_stdout="", logcat="", evidence_dir=None)

        log_path = assemble_evidence_log(evidence, tmp_path)

        assert log_path.exists()
        assert log_path.read_text() == ""


class TestRunInstrument:
    """Exit code parsing from am instrument output."""

    def test_parses_success(self):
        stdout = "INSTRUMENTATION_RESULT: status=success\n" "INSTRUMENTATION_CODE: 0\n"
        with patch("evaluation.replay_apk.subprocess.run") as mock_run:
            mock_run.return_value.stdout = stdout
            mock_run.return_value.returncode = 0

            code, output = run_instrument()

        assert code == 0
        assert "INSTRUMENTATION_CODE: 0" in output

    def test_parses_failure(self):
        stdout = "INSTRUMENTATION_CODE: 1\n"
        with patch("evaluation.replay_apk.subprocess.run") as mock_run:
            mock_run.return_value.stdout = stdout
            mock_run.return_value.returncode = 0

            code, output = run_instrument()

        assert code == 1

    def test_missing_code_returns_failure(self):
        stdout = "some garbage output\n"
        with patch("evaluation.replay_apk.subprocess.run") as mock_run:
            mock_run.return_value.stdout = stdout
            mock_run.return_value.returncode = 0

            code, _ = run_instrument()

        assert code == 1

    def test_timeout_returns_failure(self):
        import subprocess as sp

        with patch("evaluation.replay_apk.subprocess.run") as mock_run:
            mock_run.side_effect = sp.TimeoutExpired(cmd="adb", timeout=60)

            code, _ = run_instrument(timeout=60)

        assert code == 1
