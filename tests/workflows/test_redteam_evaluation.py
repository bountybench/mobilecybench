"""Tests for RedTeamWorkflow.evaluate() — task-based 2-phase pipeline.

Black-box: mocks the ops layer (run_phase, check_artifact), verifier,
and probes. Tests pipeline behavior: early stop, scoring, result structure.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from models.config import RunnerConfig
from workflows.redteam import (
    MaliciousAppOps,
    PhaseResult,
    RedTeamWorkflow,
    RemoteAttackerOps,
)

# ---------------------------------------------------------------------------
# Shared config fixtures
# ---------------------------------------------------------------------------

_BASE_CONFIG = dict(
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
    workflow="redteam",
    task="report-0",
    synthetic_vuln_id=None,
    attacker_model="malicious_app",
)


@pytest.fixture
def redteam_config():
    return RunnerConfig(**_BASE_CONFIG)


@pytest.fixture
def remote_attacker_config():
    return RunnerConfig(**{**_BASE_CONFIG, "attacker_model": "remote_attacker"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_phase_result(exit_code: int, phase_dir: Path) -> PhaseResult:
    """Create a PhaseResult with evidence log at the expected path."""
    phase_dir.mkdir(parents=True, exist_ok=True)
    evidence_log = phase_dir / "replay_evidence.log"
    evidence_log.write_text(f"exit_code={exit_code}")
    return PhaseResult(exit_code=exit_code, evidence_log_path=evidence_log)


def _make_probe_result(triggered: bool) -> dict:
    """Minimal normalized probe result."""
    return {
        "combined": {"triggered": triggered},
        "app_specific_triggered": triggered,
        "generic_triggered": triggered,
    }


def _setup_task_dir(tmp_path, app_name="testapp"):
    """Create the task directory with required files."""
    task_dir = tmp_path / "zerodays" / "reports" / app_name / "report-0" / "task"
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "fix.patch").write_text("")
    verify_dir = task_dir / "verify_files"
    verify_dir.mkdir(parents=True, exist_ok=True)
    (verify_dir / "verify_exploit.sh").write_text("#!/bin/bash\nexit 0")
    (task_dir / "prepare_app.sh").write_text("#!/bin/bash\nexit 0")
    (task_dir / "metadata.json").write_text(
        json.dumps({"attacker_model": "malicious_app", "task_id": "test-task"})
    )
    return task_dir


def _setup_malicious_app_workflow(config, tmp_path, *, create_apk=True):
    """Set up a RedTeamWorkflow for malicious_app with mocked infrastructure."""
    app_dir = tmp_path / "apps" / "testapp"
    app_dir.mkdir(parents=True)

    (app_dir / "metadata.json").write_text(
        json.dumps(
            {
                "commit_version": "abc123",
                "sdk": "34",
                "package_name": "com.test.app",
                "container_names": [],
                "app_server": "",
            }
        )
    )
    _setup_task_dir(tmp_path)
    (app_dir / "generic_probe_config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "generic_probe_applicability": {
                    "access.ssrf_detected": False,
                    "confidentiality.secrets": True,
                    "confidentiality.app_flag": False,
                    "confidentiality.container_flag": False,
                    "integrity.app_flag": False,
                    "integrity.app_pwned_file": False,
                    "integrity.container_flag": False,
                    "integrity.container_pwned_file": False,
                    "availability.check_container_health": False,
                },
            }
        )
    )
    (app_dir / "codebase").mkdir()

    wf = RedTeamWorkflow(config, "testapp", tmp_path)
    wf.metadata = json.loads((app_dir / "metadata.json").read_text())
    wf.emulator = MagicMock()

    from utils.logger import logger_manager

    exploit_dir = logger_manager.get_logs_dir() / "agent_exploit" / "exploit_apk"
    exploit_dir.mkdir(parents=True, exist_ok=True)
    if create_apk:
        (exploit_dir / "build_exploit_apk.sh").write_text("#!/bin/bash\nexit 0")
        src = exploit_dir / "src" / "com" / "mobilecybench" / "exploit"
        src.mkdir(parents=True, exist_ok=True)
        (src / "Exploit.java").write_text("class Exploit {}")
    else:
        build_script = exploit_dir / "build_exploit_apk.sh"
        if build_script.exists():
            build_script.unlink()

    return wf


def _setup_remote_attacker_workflow(config, tmp_path, *, create_exploit=True):
    """Set up a RedTeamWorkflow for remote_attacker with mocked infrastructure."""
    app_dir = tmp_path / "apps" / "testapp"
    app_dir.mkdir(parents=True)

    (app_dir / "metadata.json").write_text(
        json.dumps(
            {
                "commit_version": "abc123",
                "sdk": "34",
                "package_name": "com.test.app",
                "container_names": [],
                "app_server": "http://server:8080",
            }
        )
    )
    _setup_task_dir(tmp_path)
    (app_dir / "remote_attacker").mkdir()
    (app_dir / "codebase").mkdir()

    wf = RedTeamWorkflow(config, "testapp", tmp_path)
    wf.metadata = json.loads((app_dir / "metadata.json").read_text())
    wf.emulator = MagicMock()

    from utils.logger import logger_manager

    exploit_dir = logger_manager.get_logs_dir() / "agent_exploit"
    exploit_dir.mkdir(parents=True, exist_ok=True)
    if create_exploit:
        (exploit_dir / "exploit.sh").write_text("#!/bin/bash\nexit 0")
    else:
        exploit_sh = exploit_dir / "exploit.sh"
        if exploit_sh.exists():
            exploit_sh.unlink()

    return wf


def _run_evaluate(wf, ops_cls, phase_results, probe_results, verifier_exits=None):
    """Run evaluate() with mocked ops, verifier, and probes.

    verifier_exits: list of exit codes for each _run_verifier call.
                   Defaults to [1, 1] (verifier says not vulnerable).
    """
    if verifier_exits is None:
        verifier_exits = [1] * (len(phase_results) * 2)

    phase_idx = [0]

    def fake_run_phase(workflow, phase_dir, **kwargs):
        i = phase_idx[0]
        phase_idx[0] += 1
        return _make_phase_result(phase_results[i], phase_dir)

    probe_idx = [0]

    def fake_normalize(*args):
        i = probe_idx[0]
        probe_idx[0] += 1
        return _make_probe_result(probe_results[i])

    verifier_idx = [0]

    def fake_verifier(phase_dir):
        i = verifier_idx[0]
        verifier_idx[0] += 1
        return verifier_exits[i]

    with (
        patch.object(ops_cls, "run_phase", side_effect=fake_run_phase),
        patch.object(RedTeamWorkflow, "_run_checks", return_value=True),
        patch.object(RedTeamWorkflow, "_run_verifier", side_effect=fake_verifier),
        patch(
            "evaluation.unified_metrics.normalize_probe_results",
            side_effect=fake_normalize,
        ),
        patch("subprocess.run"),
    ):
        return wf.evaluate()


# ---------------------------------------------------------------------------
# Artifact checks
# ---------------------------------------------------------------------------


class TestArtifactCheck:
    """Ops.check_artifact validates exploit layout in agent_exploit/."""

    def test_app_ops_finds_buildable_project(self, tmp_path):
        apk_dir = tmp_path / "exploit_apk"
        apk_dir.mkdir()
        (apk_dir / "build_exploit_apk.sh").write_text("#!/bin/bash\nexit 0")
        src = apk_dir / "src" / "com" / "mobilecybench" / "exploit"
        src.mkdir(parents=True)
        (src / "Exploit.java").write_text("class Exploit {}")
        ok, _ = MaliciousAppOps().check_artifact(tmp_path)
        assert ok is True

    def test_app_ops_missing_build_script(self, tmp_path):
        ok, msg = MaliciousAppOps().check_artifact(tmp_path)
        assert ok is False
        assert "build_exploit_apk.sh" in msg

    def test_app_ops_missing_java_sources(self, tmp_path):
        apk_dir = tmp_path / "exploit_apk"
        apk_dir.mkdir()
        (apk_dir / "build_exploit_apk.sh").write_text("#!/bin/bash\nexit 0")
        ok, msg = MaliciousAppOps().check_artifact(tmp_path)
        assert ok is False
        assert "Java sources" in msg

    def test_remote_ops_finds_exploit_sh(self, tmp_path):
        (tmp_path / "exploit.sh").write_text("#!/bin/bash\nexit 0")
        ok, _ = RemoteAttackerOps().check_artifact(tmp_path)
        assert ok is True

    def test_remote_ops_missing_exploit_sh(self, tmp_path):
        ok, msg = RemoteAttackerOps().check_artifact(tmp_path)
        assert ok is False
        assert "exploit.sh" in msg


# ---------------------------------------------------------------------------
# Malicious app — pipeline behavior
# ---------------------------------------------------------------------------


class TestExploitMissing:
    def test_no_apk_scores_zero(self, redteam_config, tmp_path):
        wf = _setup_malicious_app_workflow(redteam_config, tmp_path, create_apk=False)
        result = wf.evaluate()
        assert result["status"] == "exploit_missing"
        assert result["score"] == 0


class TestEarlyStop:
    """Phase 1 fails AND no probes/verifier triggered → skip Phase 2."""

    def test_early_stop_skips_phase2(self, redteam_config, tmp_path):
        wf = _setup_malicious_app_workflow(redteam_config, tmp_path)
        result = _run_evaluate(wf, MaliciousAppOps, [1], [False])
        assert result["status"] == "no_impact"
        assert result["score"] == 0

    def test_verifier_bypasses_early_stop(self, redteam_config, tmp_path):
        """Phase 1 fails and probes don't trigger, but verifier fires → phase 2 runs."""
        wf = _setup_malicious_app_workflow(redteam_config, tmp_path)
        # Verifier: phase1=0 (vuln confirmed), phase2=1 (patched)
        result = _run_evaluate(
            wf, MaliciousAppOps, [1, 1], [False, False], verifier_exits=[0, 1]
        )
        assert result["status"] == "verified"
        assert result["score"] == 1
        assert result["signals"]["verifier_diff"] == 1


class TestResultStructure:
    """Result JSON has expected fields and is persisted."""

    def test_result_saved_to_file(self, redteam_config, tmp_path):
        wf = _setup_malicious_app_workflow(redteam_config, tmp_path, create_apk=False)
        wf.evaluate()
        scores_file = tmp_path / "apps" / "testapp" / "redteam_scores.json"
        assert scores_file.exists()
        data = json.loads(scores_file.read_text())
        assert data["status"] == "exploit_missing"
        assert data["task"] == "report-0"


class TestPatchRestoration:
    """fix.patch is always restored even if phase 2 crashes."""

    def test_git_checkout_called_on_phase2_exception(self, redteam_config, tmp_path):
        wf = _setup_malicious_app_workflow(redteam_config, tmp_path)
        call_count = [0]

        def fake_run_phase(workflow, phase_dir, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_phase_result(0, phase_dir)
            raise RuntimeError("phase 2 infra crash")

        subprocess_calls = []

        def tracking_run(cmd, **kwargs):
            subprocess_calls.append(cmd)

        with (
            patch.object(MaliciousAppOps, "run_phase", side_effect=fake_run_phase),
            patch.object(RedTeamWorkflow, "_run_checks", return_value=True),
            patch.object(RedTeamWorkflow, "_run_verifier", return_value=1),
            patch(
                "evaluation.unified_metrics.normalize_probe_results",
                return_value=_make_probe_result(True),
            ),
            patch("subprocess.run", side_effect=tracking_run),
        ):
            with pytest.raises(RuntimeError, match="phase 2 infra crash"):
                wf.evaluate()

        checkout_calls = [
            c for c in subprocess_calls if c == ["git", "checkout", "--", "."]
        ]
        # TaskBundle hooks: prepare_phase1 (1), prepare_phase2 (2), finally (3).
        assert len(checkout_calls) == 3


# ---------------------------------------------------------------------------
# Remote attacker — pipeline behavior
# ---------------------------------------------------------------------------


class TestRemoteAttackerValidation:
    def test_missing_probe_dir_rejected(self, remote_attacker_config, tmp_path):
        app_dir = tmp_path / "apps" / "testapp"
        app_dir.mkdir(parents=True)
        (app_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "commit_version": "abc123",
                    "sdk": "34",
                    "package_name": "com.test.app",
                    "container_names": [],
                }
            )
        )
        _setup_task_dir(tmp_path)
        wf = RedTeamWorkflow(remote_attacker_config, "testapp", tmp_path)
        with pytest.raises(
            ValueError, match="remote_attacker probe directory not found"
        ):
            wf.validate_arguments()


class TestRemoteAttackerPhaseSequence:
    """Verify remote_attacker phase ordering: exploit → pm clear → prepare_app."""

    def test_exploit_then_clear_then_prepare(self, remote_attacker_config, tmp_path):
        wf = _setup_remote_attacker_workflow(remote_attacker_config, tmp_path)
        call_order = []

        def track_run_exploit(*args, **kwargs):
            call_order.append("exploit")
            phase_dir = args[1]
            phase_dir.mkdir(parents=True, exist_ok=True)
            evidence = phase_dir / "replay_evidence.log"
            evidence.write_text("test")
            return {
                "replay_exit_code": 1,
                "replay_stdout": "",
                "replay_stderr": "",
                "replay_evidence_path": str(evidence),
            }

        def track_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and "pm" in cmd and "clear" in cmd:
                call_order.append("pm_clear")
            return MagicMock(returncode=0)

        def track_prepare_app():
            call_order.append("prepare_app")

        with (
            patch.object(RedTeamWorkflow, "_restart_runtime"),
            patch.object(
                RedTeamWorkflow, "_run_exploit", side_effect=track_run_exploit
            ),
            patch("workflows.redteam.subprocess.run", side_effect=track_subprocess_run),
            patch.object(
                RedTeamWorkflow, "_run_prepare_app", side_effect=track_prepare_app
            ),
            patch.object(RedTeamWorkflow, "_run_checks", return_value=True),
            patch.object(RedTeamWorkflow, "_run_verifier", return_value=1),
            patch(
                "evaluation.unified_metrics.normalize_probe_results",
                return_value=_make_probe_result(False),
            ),
        ):
            wf.evaluate()

        assert call_order == ["exploit", "pm_clear", "prepare_app"]

    def test_prepare_app_failure_returns_failed_phase(
        self, remote_attacker_config, tmp_path
    ):
        """If prepare_app crashes, run_phase returns exit_code=2."""
        wf = _setup_remote_attacker_workflow(remote_attacker_config, tmp_path)

        def fake_run_exploit(*args, **kwargs):
            phase_dir = args[1]
            phase_dir.mkdir(parents=True, exist_ok=True)
            return {
                "replay_exit_code": 0,
                "replay_stdout": "",
                "replay_stderr": "",
                "replay_evidence_path": None,
            }

        with (
            patch.object(RedTeamWorkflow, "_restart_runtime"),
            patch.object(RedTeamWorkflow, "_run_exploit", side_effect=fake_run_exploit),
            patch(
                "workflows.redteam.subprocess.run", return_value=MagicMock(returncode=0)
            ),
            patch.object(
                RedTeamWorkflow,
                "_run_prepare_app",
                side_effect=RuntimeError("prepare_app timed out"),
            ),
        ):
            result = RemoteAttackerOps().run_phase(
                wf,
                tmp_path / "phase_test",
                exploit_dir=tmp_path,
                target_apk=Path("apk/test.apk"),
            )
            assert result.exit_code == 2
            assert result.evidence_log_path is None


# ---------------------------------------------------------------------------
# setup_runtime_environment wires bundle phase-1 state for live-agent runs
# ---------------------------------------------------------------------------


class TestSetupRuntimeEnvironmentLiveAgentWiring:
    """The agent must see Phase 1 state, not the clean baseline.

    Regression guard for the synthetic-redteam case: without this, the agent
    analyzes the clean codebase and an APK that doesn't match what Phase 1
    installs, producing exploits against the wrong target state.
    """

    def test_installs_bundle_phase1_apk(self, redteam_config, tmp_path):
        """install_app_and_setup_backend gets bundle.phase1_apk()."""
        wf = _setup_malicious_app_workflow(redteam_config, tmp_path)
        phase1 = wf._bundle.phase1_apk()

        captured = {}

        def fake_install(app_dir, emulator, project_root, **kwargs):
            captured["apk_path"] = kwargs.get("apk_path")

        with (
            patch("utils.emulator_manager.EmulatorManager", return_value=MagicMock()),
            patch.object(RedTeamWorkflow, "setup_apks"),
            patch.object(type(wf._bundle), "validate_build_artifacts"),
            patch("utils.emulator_certs.inject_system_ca"),
            patch(
                "utils.setup_utils.install_app_and_setup_backend",
                side_effect=fake_install,
            ),
            patch(
                "agent.agent_container.setup_agent_environment",
                return_value=MagicMock(),
            ),
            patch("utils.setup_utils.check_connectivity"),
            patch.object(MaliciousAppOps, "setup_agent_extras"),
        ):
            wf.setup_runtime_environment()

        assert captured["apk_path"] == phase1

    def test_forwards_bundle_prepare_phase1_as_post_checkout_hook(
        self, redteam_config, tmp_path
    ):
        """setup_agent_environment receives bundle.prepare_phase1_codebase."""
        wf = _setup_malicious_app_workflow(redteam_config, tmp_path)

        captured = {}

        def fake_setup_agent(**kwargs):
            captured["post_checkout_hook"] = kwargs.get("post_checkout_hook")
            return MagicMock()

        with (
            patch("utils.emulator_manager.EmulatorManager", return_value=MagicMock()),
            patch.object(RedTeamWorkflow, "setup_apks"),
            patch.object(type(wf._bundle), "validate_build_artifacts"),
            patch("utils.emulator_certs.inject_system_ca"),
            patch("utils.setup_utils.install_app_and_setup_backend"),
            patch(
                "agent.agent_container.setup_agent_environment",
                side_effect=fake_setup_agent,
            ),
            patch("utils.setup_utils.check_connectivity"),
            patch.object(MaliciousAppOps, "setup_agent_extras"),
        ):
            wf.setup_runtime_environment()

        # For zeroday (test's redteam_config uses task="report-0"),
        # prepare_phase1_codebase is a no-op git-restore. Assertion checks
        # that the hook is the bundle's bound method, not None or something
        # else.
        assert captured["post_checkout_hook"] == wf._bundle.prepare_phase1_codebase
