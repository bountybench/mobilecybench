"""Tests for malicious APK replay — evidence assembly and exit code parsing."""

import subprocess
from unittest.mock import patch

import pytest

from evaluation import replay_apk
from evaluation.replay_apk import (
    EvidenceBundle,
    assemble_evidence_log,
    manifest_declares_permission,
    run_instrument,
)


def _completed(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


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


class TestManifestDeclaresPermission:
    def test_detects_read_logs_permission(self, tmp_path):
        (tmp_path / "AndroidManifest.xml").write_text(
            """<?xml version=\"1.0\" encoding=\"utf-8\"?>
<manifest xmlns:android=\"http://schemas.android.com/apk/res/android\">
    <uses-permission android:name=\"android.permission.READ_LOGS\" />
</manifest>
"""
        )

        assert manifest_declares_permission(tmp_path, "android.permission.READ_LOGS")

    def test_ignores_absent_permission(self, tmp_path):
        (tmp_path / "AndroidManifest.xml").write_text(
            """<?xml version=\"1.0\" encoding=\"utf-8\"?>
<manifest xmlns:android=\"http://schemas.android.com/apk/res/android\">
    <uses-permission android:name=\"android.permission.INTERNET\" />
</manifest>
"""
        )

        assert not manifest_declares_permission(tmp_path, "android.permission.READ_LOGS")

    def test_missing_manifest_returns_false(self, tmp_path):
        assert not manifest_declares_permission(tmp_path, "android.permission.READ_LOGS")


_DIALOG_XML = (
    "<hierarchy>"
    '<node resource-id="com.android.systemui:id/log_access_dialog_allow_button" '
    'bounds="[100,200][300,400]" />'
    "</hierarchy>"
)
_EMPTY_XML = "<hierarchy></hierarchy>"


def _adb_responder(prefix_matchers):
    """Build a _run_adb side_effect from (prefix, response-or-callable) pairs.

    First matching prefix wins. Unmatched commands return a success result.
    Callables receive the args list and may pop from a per-test queue.
    """
    def side_effect(args, _timeout=20):
        cmd = " ".join(args)
        for prefix, response in prefix_matchers:
            if cmd.startswith(prefix):
                return response(args) if callable(response) else response
        return _completed()
    return side_effect


class TestApproveLogAccessDialog:
    """Polling-based dialog approval — never blind-taps."""

    def test_taps_button_when_dialog_visible(self):
        side_effect = _adb_responder([
            ("exec-out cat", _completed(stdout=_DIALOG_XML)),
        ])

        with patch.object(replay_apk, "_run_adb", side_effect=side_effect) as mock:
            replay_apk._approve_log_access_dialog(timeout=2, interval=0.01)

        # Bounds [100,200][300,400] → center (200, 300)
        tap_calls = [c.args[0] for c in mock.call_args_list if c.args[0][:3] == ["shell", "input", "tap"]]
        assert tap_calls == [["shell", "input", "tap", "200", "300"]]

    def test_raises_when_dialog_never_appears(self):
        side_effect = _adb_responder([
            ("exec-out cat", _completed(stdout=_EMPTY_XML)),
        ])

        with patch.object(replay_apk, "_run_adb", side_effect=side_effect):
            with pytest.raises(RuntimeError, match="did not appear"):
                replay_apk._approve_log_access_dialog(timeout=0.2, interval=0.05)

    def test_retries_after_parse_error(self):
        queue = [_completed(stdout="not xml at all"), _completed(stdout=_DIALOG_XML)]
        side_effect = _adb_responder([
            ("exec-out cat", lambda _args: queue.pop(0) if queue else _completed(stdout=_EMPTY_XML)),
        ])

        with patch.object(replay_apk, "_run_adb", side_effect=side_effect):
            replay_apk._approve_log_access_dialog(timeout=2, interval=0.01)

    def test_raises_on_malformed_bounds(self):
        broken_xml = (
            "<hierarchy>"
            '<node resource-id="com.android.systemui:id/log_access_dialog_allow_button" '
            'bounds="bogus" />'
            "</hierarchy>"
        )
        side_effect = _adb_responder([
            ("exec-out cat", _completed(stdout=broken_xml)),
        ])

        with patch.object(replay_apk, "_run_adb", side_effect=side_effect):
            with pytest.raises(RuntimeError, match="Malformed bounds"):
                replay_apk._approve_log_access_dialog(timeout=2, interval=0.01)


class TestEnableReadLogsAccess:
    """End-to-end: pm grant + launch + dialog approve + force-stop."""

    def test_grants_and_approves(self):
        side_effect = _adb_responder([
            ("exec-out cat", _completed(stdout=_DIALOG_XML)),
        ])

        with patch.object(replay_apk, "_run_adb", side_effect=side_effect) as mock:
            replay_apk.enable_read_logs_access(timeout=2)

        commands = [" ".join(c.args[0]) for c in mock.call_args_list]
        assert any(c.startswith("shell pm grant") and "READ_LOGS" in c for c in commands)
        assert any(c.startswith("shell am start") for c in commands)
        assert any(c.startswith("shell input tap") for c in commands)
        assert any(c.startswith("shell am force-stop") for c in commands)

    def test_raises_when_pm_grant_fails(self):
        side_effect = _adb_responder([
            ("shell pm grant", _completed(returncode=1, stderr="not found")),
        ])

        with patch.object(replay_apk, "_run_adb", side_effect=side_effect):
            with pytest.raises(RuntimeError, match="pm grant READ_LOGS failed"):
                replay_apk.enable_read_logs_access(timeout=2)

    def test_raises_when_launch_fails(self):
        side_effect = _adb_responder([
            ("shell am start", _completed(returncode=1, stderr="no activity")),
        ])

        with patch.object(replay_apk, "_run_adb", side_effect=side_effect):
            with pytest.raises(RuntimeError, match="MainActivity"):
                replay_apk.enable_read_logs_access(timeout=2)

    def test_warns_when_dialog_absent(self, caplog):
        """Missing dialog must not abort replay — verifier surfaces real failures."""
        side_effect = _adb_responder([
            ("exec-out cat", _completed(stdout=_EMPTY_XML)),
        ])

        with patch.object(replay_apk, "_run_adb", side_effect=side_effect):
            with caplog.at_level("WARNING"):
                replay_apk.enable_read_logs_access(timeout=0.1)

        assert any("consent dialog approval skipped" in r.message for r in caplog.records)
