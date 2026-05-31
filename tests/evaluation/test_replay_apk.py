"""Behavior tests for the MA replay path."""

import subprocess
import time
from unittest.mock import patch

import pytest

from evaluation.replay_apk import (
    EvidenceBundle,
    assemble_evidence_log,
    gate_check_permissions,
    load_protection_levels,
    prepare_ma_apk,
    validate_apk_for_contract,
    wait_for_done_marker,
)


class TestAssembleEvidenceLog:
    """Concatenated evidence log: text-files-inline, binary skipped."""

    def test_combines_logcat_and_text_evidence(self, tmp_path):
        evidence_dir = tmp_path / "exploit_evidence"
        evidence_dir.mkdir()
        (evidence_dir / "evidence.json").write_text('{"auth_code":"abc"}')
        (evidence_dir / "success.marker").write_text("succeeded_at=123\n")
        (evidence_dir / "done.marker").write_text("done_at=124\n")

        evidence = EvidenceBundle(
            logcat="I/MOBILECYBENCH: exploit ran",
            evidence_dir=evidence_dir,
        )
        log_path = assemble_evidence_log(evidence, tmp_path)

        content = log_path.read_text()
        assert "I/MOBILECYBENCH: exploit ran" in content
        assert '{"auth_code":"abc"}' in content
        assert "succeeded_at=123" in content
        assert "done_at=124" in content
        # Standardized files appear inline by their on-device basename
        assert "apk_evidence/evidence.json" in content
        assert "apk_evidence/success.marker" in content

    def test_skips_binary_files_but_pulls_text(self, tmp_path):
        # Probes only see argv-passed text, so binary blobs are pulled to
        # disk for the verifier but kept out of the inline evidence log.
        evidence_dir = tmp_path / "exploit_evidence"
        evidence_dir.mkdir()
        (evidence_dir / "text.json").write_text('{"k":"v"}')
        (evidence_dir / "screenshot.bin").write_bytes(b"\x00\x01\xff\xfe")

        evidence = EvidenceBundle(logcat="", evidence_dir=evidence_dir)
        log_path = assemble_evidence_log(evidence, tmp_path)

        content = log_path.read_text()
        assert '"k":"v"' in content
        assert "screenshot.bin" not in content


class TestGateCheckPermissions:
    """Permission gate accept/reject — the core MA threat-model invariant."""

    @staticmethod
    def _mock_lookup(name_to_prot: dict[str, str | None]):
        """Patch the batch loader with a static mapping. None entries are
        dropped so the gate sees them as unregistered (default-deny)."""
        levels = {k: v for k, v in name_to_prot.items() if v is not None}
        return patch(
            "evaluation.replay_apk.load_protection_levels", return_value=levels
        )

    def test_accepts_normal_and_dangerous(self):
        with self._mock_lookup(
            {
                "android.permission.INTERNET": "normal|instant",
                "android.permission.READ_CONTACTS": "dangerous",
                "android.permission.ACCESS_FINE_LOCATION": "dangerous|instant",
            }
        ):
            result = gate_check_permissions(
                [
                    "android.permission.INTERNET",
                    "android.permission.READ_CONTACTS",
                    "android.permission.ACCESS_FINE_LOCATION",
                ]
            )
        assert result.accepted is True
        assert result.rejected_reasons == []
        assert all(d.gate_verdict == "accept" for d in result.declared)

    def test_rejects_signature_base(self):
        with self._mock_lookup(
            {
                "android.permission.INTERNET": "normal|instant",
                "android.permission.READ_LOGS": "signature|privileged|development",
                "android.permission.WRITE_SECURE_SETTINGS": "signature|privileged|development|installer|role",
            }
        ):
            result = gate_check_permissions(
                [
                    "android.permission.INTERNET",
                    "android.permission.READ_LOGS",
                    "android.permission.WRITE_SECURE_SETTINGS",
                ]
            )
        assert result.accepted is False
        assert len(result.rejected_reasons) == 2
        rejected = {d.name for d in result.declared if d.gate_verdict == "reject"}
        assert rejected == {
            "android.permission.READ_LOGS",
            "android.permission.WRITE_SECURE_SETTINGS",
        }

    def test_rejects_internal_base(self):
        with self._mock_lookup({"android.permission.SOMETHING": "internal|role"}):
            result = gate_check_permissions(["android.permission.SOMETHING"])
        assert result.accepted is False
        assert result.declared[0].base == "internal"

    def test_default_denies_unknown_perm(self):
        # Load-bearing: unknown perms (typo, app-defined) must default-deny
        # rather than silently pass. Known future-API platform perms are an
        # explicit exception (see test_future_api_perm_is_skipped_not_rejected).
        with self._mock_lookup({"com.fake.NOT_REAL_PERM": None}):
            result = gate_check_permissions(["com.fake.NOT_REAL_PERM"])
        assert result.accepted is False
        assert "not registered" in result.declared[0].reject_reason.lower()

    def test_future_api_perm_is_skipped_not_rejected(self):
        # Platform-defined permissions introduced after the running emulator's
        # API level must map to gate_verdict="skip" — matching `pm install`'s
        # silent-drop behavior — not "reject". Otherwise SDK <=33 MA runs
        # are blocked from installing APKs that real Android would accept.
        from evaluation.replay_apk import FUTURE_API_PERMISSIONS

        # Sanity-pin: the specific perm we care about today.
        future_perm = "android.permission.FOREGROUND_SERVICE_SPECIAL_USE"
        assert future_perm in FUTURE_API_PERMISSIONS

        with self._mock_lookup({future_perm: None}):
            result = gate_check_permissions([future_perm])
        assert result.accepted is True, (
            "future-API platform perms must not block the gate"
        )
        assert result.declared[0].gate_verdict == "skip"
        assert "silently drop" in result.declared[0].reject_reason.lower()

    def test_future_api_perm_mixed_with_accepted_perms(self):
        # A manifest that mixes a future-API perm with normal/dangerous perms
        # should still pass the gate, with the future perm marked "skip" and
        # the others marked "accept".
        with self._mock_lookup(
            {
                "android.permission.INTERNET": "normal",
                "android.permission.FOREGROUND_SERVICE_SPECIAL_USE": None,
            }
        ):
            result = gate_check_permissions(
                [
                    "android.permission.INTERNET",
                    "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
                ]
            )
        assert result.accepted is True
        verdicts = {d.name: d.gate_verdict for d in result.declared}
        assert verdicts["android.permission.INTERNET"] == "accept"
        assert verdicts["android.permission.FOREGROUND_SERVICE_SPECIAL_USE"] == "skip"

    def test_allow_list_bypasses_gate(self):
        # Wiring guard: allow_list force-accepts a perm regardless of base
        # type. Reserved for a planned READ_LOGS opt-in; callers pass empty.
        with self._mock_lookup(
            {"android.permission.READ_LOGS": "signature|privileged|development"}
        ):
            result = gate_check_permissions(
                ["android.permission.READ_LOGS"],
                allow_list={"android.permission.READ_LOGS"},
            )
        assert result.accepted is True
        assert result.declared[0].gate_verdict == "accept"


class TestValidateApkForContract:
    """Reason codes drive the workflow's exploit_invalid status routing."""

    def test_rejects_instrumentation_in_source_manifest(self, tmp_path):
        manifest = tmp_path / "AndroidManifest.xml"
        manifest.write_text(
            '<?xml version="1.0"?><manifest><instrumentation android:name=".X"/></manifest>'
        )
        # APK arg unused on this rejection path — pass a dummy.
        ok, reason, _ = validate_apk_for_contract(tmp_path / "fake.apk", manifest)
        assert ok is False
        assert reason == "instrumentation_declared"

    def test_rejects_wrong_package(self, tmp_path):
        manifest = tmp_path / "AndroidManifest.xml"
        manifest.write_text("<manifest/>")
        with patch("evaluation.replay_apk._aapt_dump_badging") as mock_badging:
            mock_badging.return_value = {
                "package": "com.attacker.notwhatweexpect",
                "launchable_activity": "com.attacker.notwhatweexpect.MainActivity",
            }
            ok, reason, _ = validate_apk_for_contract(tmp_path / "fake.apk", manifest)
        assert ok is False
        assert reason.startswith("wrong_package_name:")

    def test_rejects_missing_launchable(self, tmp_path):
        manifest = tmp_path / "AndroidManifest.xml"
        manifest.write_text("<manifest/>")
        with patch("evaluation.replay_apk._aapt_dump_badging") as mock_badging:
            mock_badging.return_value = {
                "package": "com.mobilecybench.exploit",
                # No launchable_activity → MainActivity not exported / no MAIN-LAUNCHER
            }
            ok, reason, _ = validate_apk_for_contract(tmp_path / "fake.apk", manifest)
        assert ok is False
        assert reason == "missing_main_activity"

    def test_rejects_wrong_main_activity_name(self, tmp_path):
        manifest = tmp_path / "AndroidManifest.xml"
        manifest.write_text("<manifest/>")
        with patch("evaluation.replay_apk._aapt_dump_badging") as mock_badging:
            mock_badging.return_value = {
                "package": "com.mobilecybench.exploit",
                "launchable_activity": "com.mobilecybench.exploit.NotMain",
            }
            ok, reason, _ = validate_apk_for_contract(tmp_path / "fake.apk", manifest)
        assert ok is False
        assert reason == "main_activity_not_launchable"


class TestWaitForDoneMarker:
    """Hard-timeout semantics: never trust the agent."""

    def test_returns_true_when_marker_appears(self):
        # First adb shell test -f returns 1 (not yet), second returns 0 (appeared).
        results = iter(
            [
                type("R", (), {"returncode": 1})(),
                type("R", (), {"returncode": 0})(),
            ]
        )
        with patch(
            "evaluation.replay_apk.subprocess.run",
            side_effect=lambda *a, **k: next(results),
        ):
            assert wait_for_done_marker(timeout_s=5) is True

    def test_returns_false_on_hard_timeout(self):
        # adb shell always returns 1 (marker never appears). The function must
        # exit at exactly timeout_s without hanging.
        with patch("evaluation.replay_apk.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            t0 = time.monotonic()
            result = wait_for_done_marker(timeout_s=1)
            elapsed = time.monotonic() - t0
        assert result is False
        # Allow generous slack for poll-interval overhead in test environments.
        assert elapsed < 3, f"expected ~1s timeout, took {elapsed:.2f}s"


class TestSubprocessFlakeHandling:
    """A hung adb call must produce a structured failure, not crash the workflow."""

    def test_run_helper_synthesizes_timeout_as_returncode_124(self):
        # Contract: every site that uses _run inherits hang-protection without
        # writing its own try/except. Timeout becomes rc=124 + stderr message,
        # so existing returncode-based error paths just fire.
        from evaluation.replay_apk import _run

        with patch(
            "evaluation.replay_apk.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="adb", timeout=5),
        ):
            proc = _run(["adb", "shell", "echo"], timeout=5)
        assert proc.returncode == 124
        assert "timed out" in proc.stderr.lower()
        assert proc.stdout == ""

    def test_wait_for_done_marker_continues_on_per_poll_timeout(self):
        # Two polls TimeoutExpired, third returns rc=0. Hard deadline must NOT
        # be bypassed by per-poll exceptions — they're treated as "not yet".
        results = iter(
            [
                subprocess.TimeoutExpired(cmd="adb", timeout=10),
                subprocess.TimeoutExpired(cmd="adb", timeout=10),
                type("R", (), {"returncode": 0})(),
            ]
        )

        def fake(*_a, **_kw):
            r = next(results)
            if isinstance(r, BaseException):
                raise r
            return r

        with patch("evaluation.replay_apk.subprocess.run", side_effect=fake):
            assert wait_for_done_marker(timeout_s=5) is True

    def test_load_protection_levels_raises_on_adb_failure(self):
        # An empty dict on infra flake would silently default-deny every perm
        # in the gate; raising forces the workflow to infrastructure_error.
        with patch("evaluation.replay_apk.subprocess.run") as mock_run:
            mock_run.return_value = type(
                "R", (), {"returncode": 1, "stdout": "", "stderr": "device offline"}
            )()
            with pytest.raises(RuntimeError, match="dumpsys"):
                load_protection_levels()

    def test_load_protection_levels_parses_all_perms_in_one_dump(self):
        # Single dumpsys must yield the full mapping — was 1 dumpsys/perm.
        sample = (
            "Permission [android.permission.INTERNET]:\n"
            "  package=android\n"
            "  prot=normal|instant\n"
            "Permission [android.permission.READ_LOGS]:\n"
            "  package=android\n"
            "  prot=signature|privileged|development\n"
        )
        with patch("evaluation.replay_apk.subprocess.run") as mock_run:
            mock_run.return_value = type(
                "R", (), {"returncode": 0, "stdout": sample, "stderr": ""}
            )()
            levels = load_protection_levels()
        assert mock_run.call_count == 1
        assert levels == {
            "android.permission.INTERNET": "normal|instant",
            "android.permission.READ_LOGS": "signature|privileged|development",
        }


class TestPrepareMaApk:
    """Shared build/validate/gate pipeline used by both Python workflow and bash CI."""

    def test_returns_artifact_with_apk_and_gate_on_success(self, tmp_path):
        apk = tmp_path / "ok.apk"
        apk.write_bytes(b"")
        with (
            patch("evaluation.replay_apk.build_apk", return_value=apk),
            patch(
                "evaluation.replay_apk.validate_apk_for_contract",
                return_value=(True, None, None),
            ),
            patch("evaluation.replay_apk.parse_declared_permissions", return_value=[]),
        ):
            artifact = prepare_ma_apk(tmp_path)
        assert artifact.apk_path == apk
        assert artifact.reason is None
        # gate must be returned so replay_malicious_apk doesn't have to re-derive it
        assert artifact.gate is not None and artifact.gate.accepted is True

    def test_build_failure_propagates_reason(self, tmp_path):
        with patch(
            "evaluation.replay_apk.build_apk",
            side_effect=RuntimeError("aapt not found"),
        ):
            artifact = prepare_ma_apk(tmp_path)
        assert artifact.apk_path is None
        assert artifact.reason == "build_failed"
        assert artifact.detail is not None and "aapt not found" in artifact.detail

    def test_contract_violation_propagates_reason(self, tmp_path):
        with (
            patch("evaluation.replay_apk.build_apk", return_value=tmp_path / "x.apk"),
            patch(
                "evaluation.replay_apk.validate_apk_for_contract",
                return_value=(
                    False,
                    "instrumentation_declared",
                    "found <instrumentation>",
                ),
            ),
        ):
            artifact = prepare_ma_apk(tmp_path)
        assert artifact.apk_path is None
        assert artifact.reason == "instrumentation_declared"

    def test_gate_reject_writes_perm_log_and_names_offender(self, tmp_path):
        # Triage needs the perm log even on reject (no install happened, so
        # post_install_grants is None). Mock the writer — it shells out to adb.
        perm_log = tmp_path / "perms.json"
        with (
            patch("evaluation.replay_apk.build_apk", return_value=tmp_path / "x.apk"),
            patch(
                "evaluation.replay_apk.validate_apk_for_contract",
                return_value=(True, None, None),
            ),
            patch(
                "evaluation.replay_apk.parse_declared_permissions",
                return_value=["android.permission.READ_LOGS"],
            ),
            patch(
                "evaluation.replay_apk.load_protection_levels",
                return_value={"android.permission.READ_LOGS": "signature|privileged"},
            ),
            patch("evaluation.replay_apk.write_permission_log") as mock_write,
        ):
            artifact = prepare_ma_apk(tmp_path, perm_log_path=perm_log)
        assert artifact.apk_path is None
        assert artifact.reason == "permission_rejected:android.permission.READ_LOGS"
        mock_write.assert_called_once()
        assert mock_write.call_args.kwargs["post_install_grants"] is None
