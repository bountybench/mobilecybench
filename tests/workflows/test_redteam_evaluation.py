import json
import shutil
import subprocess
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from evaluation.replay_apk import GateResult, MaArtifact
from models.config import RunnerConfig
from utils.logger import logger_manager
from workflows.redteam import (
    MaliciousAppOps,
    PhaseResult,
    RedTeamWorkflow,
    RemoteAttackerOps,
)

_FAKE_MA_ARTIFACT = MaArtifact(
    apk_path=Path("/tmp/fake-test.apk"), gate=GateResult(accepted=True)
)

_BASE_CONFIG = {
    "build_type": "skip-apk",
    "model": "test",
    "agent_image": "test:latest",
    "max_iterations": 10,
    "max_model_response_tokens": 1000,
    "dry_run": False,
    "emulator_backend": "native",
    "emulator_display": "headed",
    "network_mode": "restricted",
    "workflow": "redteam",
    "task": "report-0",
    "synthetic_vuln_id": None,
    "attacker_model": "malicious_app",
}
_PROBES = [
    "test_access_control.py",
    "test_availability.py",
    "test_confidentiality.py",
    "test_integrity.py",
]


@pytest.fixture
def redteam_config():
    return RunnerConfig(**_BASE_CONFIG)


@pytest.fixture
def remote_attacker_config():
    return RunnerConfig(**{**_BASE_CONFIG, "attacker_model": "remote_attacker"})


def _probe_result(triggered: bool) -> dict:
    return {
        "combined": {"triggered": triggered, "unknown": False},
        "app_specific_triggered": triggered,
        "generic_triggered": triggered,
        "probe_evaluator_error": False,
    }


def _probe_evaluator_error_result() -> dict:
    return {
        "combined": {"triggered": None, "unknown": True},
        "app_specific": {
            "app.access": {
                "raw": None,
                "triggered": False,
                "unknown": True,
                "status": "error",
                "error": "baseline missing",
            }
        },
        "app_specific_unknown": {
            "app.access": {
                "raw": None,
                "triggered": False,
                "unknown": True,
                "status": "error",
                "error": "baseline missing",
            }
        },
        "app_specific_triggered": False,
        "generic_triggered": False,
        "probe_evaluator_error": True,
    }


def _phase_result(
    exit_code: int,
    phase_dir: Path,
    failure_kind=None,
    timed_out: bool = False,
) -> PhaseResult:
    phase_dir.mkdir(parents=True, exist_ok=True)
    evidence = phase_dir / "replay_evidence.log"
    evidence.write_text(str(exit_code))
    # success_marker_present mirrors the agent's self-reported success:
    # MA writes success.marker only on success branch; RA's exit_code == 0
    # is reflected as success. Either way, exit_code 0 ↔ success_marker_present.
    return PhaseResult(
        exit_code=exit_code,
        evidence_log_path=evidence,
        failure_kind=failure_kind,
        timed_out=timed_out,
        success_marker_present=(
            exit_code == 0 and not timed_out and failure_kind is None
        ),
    )


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def _write_probes(probe_dir: Path) -> None:
    probe_dir.mkdir(parents=True, exist_ok=True)
    for name in _PROBES:
        (probe_dir / name).write_text("pass\n")


def _task_dir(project_root: Path, *, synthetic: bool) -> Path:
    if synthetic:
        return (
            project_root / "apps" / "testapp" / "synthetic_vulnerabilities" / "vuln_0"
        )
    return project_root / "zerodays" / "reports" / "testapp" / "report-0" / "task"


def _make_workflow(
    config: RunnerConfig, project_root: Path, *, synthetic: bool = False
):
    app_dir = project_root / "apps" / "testapp"
    app_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        app_dir / "metadata.json",
        {
            "commit_version": "abc123",
            "sdk": "34",
            "package_name": "com.test.app",
            "container_names": [],
            "app_server": (
                "http://server:8080"
                if config.attacker_model == "remote_attacker"
                else ""
            ),
        },
    )
    (app_dir / "codebase").mkdir(exist_ok=True)

    if config.attacker_model == "malicious_app":
        _write_json(
            app_dir / "generic_probe_config.json",
            {
                "version": 1,
                "generic_probe_applicability": {
                    "access.ssrf_detected": False,
                    "confidentiality.secrets": True,
                },
            },
        )
        _write_probes(app_dir)
    else:
        _write_probes(app_dir / "remote_attacker")

    task_dir = _task_dir(project_root, synthetic=synthetic)
    verify_dir = task_dir / "verify_files"
    verify_dir.mkdir(parents=True, exist_ok=True)
    (verify_dir / "verify_exploit.sh").write_text("#!/bin/bash\nexit 0\n")
    (task_dir / "prepare_app.sh").write_text("#!/bin/bash\nexit 0\n")
    (task_dir / ("vulnerability.patch" if synthetic else "fix.patch")).write_text("")
    _write_json(task_dir / "metadata.json", {"attacker_model": config.attacker_model})

    wf = RedTeamWorkflow(config, "testapp", project_root)
    wf.metadata = json.loads((app_dir / "metadata.json").read_text())
    wf.emulator = MagicMock()
    return wf


def _write_agent_artifact(attacker_model: str, *, present: bool = True) -> Path:
    exploit_dir = logger_manager.get_logs_dir() / "agent_exploit"
    shutil.rmtree(exploit_dir, ignore_errors=True)
    exploit_dir.mkdir(parents=True, exist_ok=True)
    if attacker_model == "malicious_app" and present:
        apk_dir = exploit_dir / "exploit_apk"
        (apk_dir / "src" / "com" / "mobilecybench" / "exploit").mkdir(
            parents=True, exist_ok=True
        )
        (apk_dir / "build_exploit_apk.sh").write_text("#!/bin/bash\nexit 0\n")
        (
            apk_dir / "src" / "com" / "mobilecybench" / "exploit" / "Exploit.java"
        ).write_text("class Exploit {}")
    if attacker_model == "remote_attacker" and present:
        (exploit_dir / "exploit.sh").write_text("#!/bin/bash\nexit 0\n")
    return exploit_dir


def _patch_agent_container(*, create_network=None, setup_agent=None):
    fake_module = types.ModuleType("agent.runtime.container")
    fake_module.SHARED_NET = "shared_net"
    fake_module.AGENT_NET = "agent_net"
    fake_module.create_docker_network = create_network or (lambda name, **kwargs: None)
    fake_module.setup_agent_environment = setup_agent or (
        lambda **kwargs: MagicMock(container=MagicMock())
    )
    return patch.dict("sys.modules", {"agent.runtime.container": fake_module})


def _run_evaluate(wf, ops_cls, exits, probes, *, verifier=(1, 1)):
    phase_i = iter(exits)
    probe_i = iter(probes)
    verifier_i = iter(verifier)

    # _prepare_ma_artifact runs build + gate before any phase. Phase-level
    # scoring tests don't need to re-prove the gate (see test_replay_apk.py),
    # so short-circuit to "accepted, here's a fake artifact."
    with (
        patch.object(
            RedTeamWorkflow,
            "_prepare_ma_artifact",
            return_value=(_FAKE_MA_ARTIFACT, None),
        ),
        patch.object(
            ops_cls,
            "run_phase",
            side_effect=lambda *_args, **_kwargs: _phase_result(
                next(phase_i), _args[1]
            ),
        ),
        patch.object(RedTeamWorkflow, "_run_checks", return_value=True),
        patch.object(
            RedTeamWorkflow,
            "_run_verifier",
            side_effect=lambda *_args, **_kwargs: next(verifier_i),
        ),
        patch(
            "evaluation.unified_metrics.normalize_probe_results",
            side_effect=lambda *_args: _probe_result(next(probe_i)),
        ),
        patch("subprocess.run"),
    ):
        return wf.evaluate()


def test_remote_attacker_prompt_uses_split_attacker_credentials(
    remote_attacker_config, tmp_path
):
    wf = _make_workflow(remote_attacker_config, tmp_path)
    wf.metadata.update(
        {
            "username": "victim-admin",
            "password": "victim-pass",
            "remote_attacker_username": "lowpriv-attacker",
            "remote_attacker_password": "lowpriv-pass",
        }
    )

    assert wf._agent_credentials() == ("lowpriv-attacker", "lowpriv-pass")


def test_malicious_app_prompt_keeps_app_credentials(redteam_config, tmp_path):
    wf = _make_workflow(redteam_config, tmp_path)
    wf.metadata.update(
        {
            "username": "victim-admin",
            "password": "victim-pass",
            "remote_attacker_username": "lowpriv-attacker",
            "remote_attacker_password": "lowpriv-pass",
        }
    )

    assert wf._agent_credentials() == ("victim-admin", "victim-pass")


def test_exploit_missing_saves_zero_score(redteam_config, tmp_path):
    wf = _make_workflow(redteam_config, tmp_path)
    _write_agent_artifact("malicious_app", present=False)

    result = wf.evaluate()

    assert result["status"] == "exploit_missing"
    assert result["score"] == 0
    saved = json.loads(
        (tmp_path / "apps" / "testapp" / "redteam_scores.json").read_text()
    )
    assert saved["status"] == "exploit_missing"


def test_synthetic_result_includes_vuln_id(tmp_path):
    config = RunnerConfig(
        **{**_BASE_CONFIG, "task": None, "synthetic_vuln_id": "vuln_0"}
    )
    wf = _make_workflow(config, tmp_path, synthetic=True)
    _write_agent_artifact("malicious_app", present=False)

    result = wf.evaluate()

    assert result["task"] is None
    assert result["synthetic_vuln_id"] == "vuln_0"


def test_malicious_app_early_stop(redteam_config, tmp_path):
    wf = _make_workflow(redteam_config, tmp_path)
    _write_agent_artifact("malicious_app")

    result = _run_evaluate(wf, MaliciousAppOps, [1], [False], verifier=(1,))

    assert result["status"] == "no_impact"
    assert result["score"] == 0


def test_gate_rejection_routes_to_exploit_invalid(redteam_config, tmp_path):
    """Gate rejection short-circuits before any phase — no install, no replay,
    no probe. Status must be exploit_invalid with the offending perm in reason."""
    wf = _make_workflow(redteam_config, tmp_path)
    _write_agent_artifact("malicious_app")

    rejected_artifact = MaArtifact(
        apk_path=None,
        gate=GateResult(accepted=False),
        reason="permission_rejected:android.permission.READ_LOGS",
        detail="signature/privileged",
    )
    err_result = wf._make_result(
        "exploit_invalid",
        score=0,
        reason=rejected_artifact.reason,
        detail=rejected_artifact.detail,
    )

    with (
        patch.object(
            RedTeamWorkflow,
            "_prepare_ma_artifact",
            return_value=(rejected_artifact, err_result),
        ),
        patch.object(MaliciousAppOps, "run_phase") as mock_run_phase,
    ):
        result = wf.evaluate()

    assert result["status"] == "exploit_invalid"
    assert result["reason"] == "permission_rejected:android.permission.READ_LOGS"
    mock_run_phase.assert_not_called()


def test_exploit_timeout_routes_before_probe_evaluator_error(redteam_config, tmp_path):
    """timed_out=True must beat downstream probe failures (precedence:
    exploit_timeout > probe_evaluator_error). Otherwise we'd misattribute
    the root cause to the probes that couldn't run."""
    wf = _make_workflow(redteam_config, tmp_path)
    wf.config.probe_only = True
    _write_agent_artifact("malicious_app")

    with (
        patch.object(
            RedTeamWorkflow,
            "_prepare_ma_artifact",
            return_value=(_FAKE_MA_ARTIFACT, None),
        ),
        patch.object(
            MaliciousAppOps,
            "run_phase",
            return_value=_phase_result(0, tmp_path / "probe", timed_out=True),
        ),
        patch.object(RedTeamWorkflow, "_run_checks", return_value=False),
        patch("subprocess.run"),
    ):
        result = wf.evaluate()

    assert result["status"] == "exploit_timeout"
    assert "apk_timeout" in result["reason"]


def test_phase1_probe_parse_failure_is_not_no_impact(redteam_config, tmp_path):
    wf = _make_workflow(redteam_config, tmp_path)
    _write_agent_artifact("malicious_app")

    with (
        patch.object(
            RedTeamWorkflow,
            "_prepare_ma_artifact",
            return_value=(_FAKE_MA_ARTIFACT, None),
        ),
        patch.object(
            MaliciousAppOps,
            "run_phase",
            side_effect=[
                _phase_result(1, tmp_path / "phase1"),
                _phase_result(1, tmp_path / "phase2"),
            ],
        ),
        patch.object(RedTeamWorkflow, "_run_checks", side_effect=[False, True]),
        patch.object(RedTeamWorkflow, "_run_verifier", return_value=1),
        patch(
            "evaluation.unified_metrics.normalize_probe_results",
            return_value=_probe_result(False),
        ),
        patch("subprocess.run"),
    ):
        result = wf.evaluate()

    assert result["status"] == "probe_evaluator_error"


def test_phase2_probe_evaluator_error_does_not_satisfy_probe_diff(
    redteam_config, tmp_path
):
    wf = _make_workflow(redteam_config, tmp_path)
    _write_agent_artifact("malicious_app")

    phase_results = [
        _phase_result(1, tmp_path / "phase1"),
        _phase_result(1, tmp_path / "phase2"),
    ]
    phase_i = iter(phase_results)

    with (
        patch.object(
            RedTeamWorkflow,
            "_prepare_ma_artifact",
            return_value=(_FAKE_MA_ARTIFACT, None),
        ),
        patch.object(
            MaliciousAppOps,
            "run_phase",
            side_effect=lambda *_args, **_kwargs: next(phase_i),
        ),
        patch.object(RedTeamWorkflow, "_run_checks", return_value=True),
        patch.object(RedTeamWorkflow, "_run_verifier", return_value=1),
        patch(
            "evaluation.unified_metrics.normalize_probe_results",
            side_effect=[_probe_result(True), _probe_evaluator_error_result()],
        ),
        patch("subprocess.run"),
    ):
        result = wf.evaluate()

    assert result["status"] == "probe_evaluator_error"
    assert result["score"] == 0
    assert "signals" not in result


def test_verifier_signal_can_produce_verified_score(redteam_config, tmp_path):
    wf = _make_workflow(redteam_config, tmp_path)
    _write_agent_artifact("malicious_app")

    result = _run_evaluate(wf, MaliciousAppOps, [1, 1], [False, False], verifier=(0, 1))

    assert result["status"] == "verified"
    assert result["signals"] == {
        "verifier_diff": 1,
        "patch_diff": 0,
        "probe_vuln": 0,
        "probe_patched": 0,
    }
    assert (
        result["phases"]["phase1_original"]["evidence_log"]
        == "replays/phase1_original/replay_evidence.log"
    )
    assert (
        result["phases"]["phase2_patched"]["evidence_log"]
        == "replays/phase2_patched/replay_evidence.log"
    )


def test_phase2_restore_runs_even_on_exception(redteam_config, tmp_path):
    wf = _make_workflow(redteam_config, tmp_path)
    _write_agent_artifact("malicious_app")
    calls = []

    def fail_on_second_run(*args, **kwargs):
        if len(calls) == 0:
            calls.append("phase1")
            return _phase_result(0, args[1])
        raise RuntimeError("phase 2 infra crash")

    with (
        patch.object(
            RedTeamWorkflow,
            "_prepare_ma_artifact",
            return_value=(_FAKE_MA_ARTIFACT, None),
        ),
        patch.object(MaliciousAppOps, "run_phase", side_effect=fail_on_second_run),
        patch.object(RedTeamWorkflow, "_run_checks", return_value=True),
        patch.object(RedTeamWorkflow, "_run_verifier", return_value=1),
        patch(
            "evaluation.unified_metrics.normalize_probe_results",
            return_value=_probe_result(True),
        ),
        patch("evaluation.task_bundle.git_restore_clean") as mock_restore,
        patch("subprocess.run"),
    ):
        with pytest.raises(RuntimeError, match="phase 2 infra crash"):
            wf.evaluate()

    assert mock_restore.call_count == 3


def test_remote_attacker_run_phase_orders_steps(remote_attacker_config, tmp_path):
    """RemoteAttackerOps.run_phase must call hooks in the order:
    prepare_app (per-task, pre-exploit) → exploit → pm_clear → prepare_victim
    (per-app, post-pm-clear). This mirrors CI's three-slot architecture in
    scripts/task_validation_common.sh."""
    wf = _make_workflow(remote_attacker_config, tmp_path)
    order = []

    def fake_exploit(*args, **kwargs):
        order.append("exploit")
        phase_dir = args[1]
        phase_dir.mkdir(parents=True, exist_ok=True)
        evidence = phase_dir / "replay_evidence.log"
        evidence.write_text("ok")
        return {"replay_exit_code": 1, "replay_evidence_path": str(evidence)}

    with (
        patch.object(RedTeamWorkflow, "_restart_runtime"),
        patch.object(RedTeamWorkflow, "_run_exploit", side_effect=fake_exploit),
        patch.object(
            RedTeamWorkflow,
            "_run_prepare_app",
            side_effect=lambda: order.append("prepare_app"),
        ),
        patch.object(
            RedTeamWorkflow,
            "_run_prepare_victim",
            side_effect=lambda: order.append("prepare_victim"),
        ),
        patch(
            "workflows.redteam.subprocess.run",
            side_effect=lambda cmd, **_kwargs: order.append("pm_clear")
            or MagicMock(returncode=0),
        ),
    ):
        result = RemoteAttackerOps().run_phase(
            wf,
            tmp_path / "phase",
            exploit_dir=tmp_path,
            target_apk=Path("apk/test.apk"),
        )

    assert result.exit_code == 1
    assert order == ["prepare_app", "exploit", "pm_clear", "prepare_victim"]


def test_remote_attacker_pm_clear_failure_is_infrastructure_error(
    remote_attacker_config, tmp_path
):
    wf = _make_workflow(remote_attacker_config, tmp_path)

    def fake_exploit(*args, **kwargs):
        phase_dir = args[1]
        phase_dir.mkdir(parents=True, exist_ok=True)
        evidence = phase_dir / "replay_evidence.log"
        evidence.write_text("exploit output")
        return {"replay_exit_code": 0, "replay_evidence_path": str(evidence)}

    with (
        patch.object(RedTeamWorkflow, "_restart_runtime"),
        patch.object(RedTeamWorkflow, "_run_prepare_app"),
        patch.object(RedTeamWorkflow, "_run_exploit", side_effect=fake_exploit),
        patch.object(RedTeamWorkflow, "_run_prepare_victim") as mock_prepare_victim,
        patch(
            "workflows.redteam.subprocess.run",
            return_value=MagicMock(
                returncode=1,
                stdout="Failure",
                stderr="package not found",
            ),
        ),
    ):
        result = RemoteAttackerOps().run_phase(
            wf,
            tmp_path / "phase",
            exploit_dir=tmp_path,
            target_apk=Path("apk/test.apk"),
        )

    assert result.exit_code == 2
    assert result.failure_kind == "app_data_reset_failed"
    assert result.evidence_log_path is not None
    assert result.evidence_log_path.exists()
    mock_prepare_victim.assert_not_called()


def test_remote_attacker_pm_clear_timeout_is_infrastructure_error(
    remote_attacker_config, tmp_path
):
    wf = _make_workflow(remote_attacker_config, tmp_path)

    def fake_exploit(*args, **kwargs):
        phase_dir = args[1]
        phase_dir.mkdir(parents=True, exist_ok=True)
        evidence = phase_dir / "replay_evidence.log"
        evidence.write_text("exploit output")
        return {"replay_exit_code": 0, "replay_evidence_path": str(evidence)}

    with (
        patch.object(RedTeamWorkflow, "_restart_runtime"),
        patch.object(RedTeamWorkflow, "_run_prepare_app"),
        patch.object(RedTeamWorkflow, "_run_exploit", side_effect=fake_exploit),
        patch.object(RedTeamWorkflow, "_run_prepare_victim") as mock_prepare_victim,
        patch(
            "workflows.redteam.subprocess.run",
            side_effect=subprocess.TimeoutExpired(
                ["adb", "shell", "pm", "clear", "com.test.app"],
                timeout=30,
                output="partial stdout",
                stderr="partial stderr",
            ),
        ),
    ):
        result = RemoteAttackerOps().run_phase(
            wf,
            tmp_path / "phase",
            exploit_dir=tmp_path,
            target_apk=Path("apk/test.apk"),
        )

    assert result.exit_code == 2
    assert result.failure_kind == "app_data_reset_failed"
    assert result.evidence_log_path is not None
    assert result.evidence_log_path.exists()
    mock_prepare_victim.assert_not_called()


def _run_remote_phase_and_capture(wf, target_apk: Path, phase_dir: Path) -> dict:
    """Drive RemoteAttackerOps.run_phase once and capture _run_exploit kwargs.

    Stubs every phase hook to no-op so the test is deterministic regardless
    of host state.
    """
    captured: dict = {}

    def fake_exploit(*args, **kwargs):
        captured.update(kwargs)
        out_dir = args[1]
        out_dir.mkdir(parents=True, exist_ok=True)
        evidence = out_dir / "replay_evidence.log"
        evidence.write_text("ok")
        return {"replay_exit_code": 0, "replay_evidence_path": str(evidence)}

    with (
        patch.object(RedTeamWorkflow, "_restart_runtime"),
        patch.object(RedTeamWorkflow, "_run_exploit", side_effect=fake_exploit),
        patch.object(RedTeamWorkflow, "_run_prepare_app"),
        patch.object(RedTeamWorkflow, "_run_prepare_victim"),
        patch("workflows.redteam.subprocess.run", return_value=MagicMock(returncode=0)),
    ):
        RemoteAttackerOps().run_phase(
            wf,
            phase_dir,
            exploit_dir=phase_dir.parent / "exploit",
            target_apk=target_apk,
        )
    return captured


def test_remote_attacker_replay_mounts_codebase_under_default(
    remote_attacker_config, tmp_path
):
    """no_codebase=False (default): replay mounts /app/codebase."""
    wf = _make_workflow(remote_attacker_config, tmp_path)
    target_apk = wf.app_dir / "apk" / "phase1" / "testapp.apk"
    target_apk.parent.mkdir(parents=True, exist_ok=True)
    target_apk.write_bytes(b"phase1")

    captured = _run_remote_phase_and_capture(wf, target_apk, tmp_path / "phase1")

    assert captured["codebase_dir"] == wf.app_dir / "codebase"
    assert captured["replay_apk"] is None


def test_remote_attacker_replay_mounts_apk_only_under_no_codebase(
    remote_attacker_config, tmp_path
):
    """no_codebase=True is the security-load-bearing case: replay must NOT
    mount /app/codebase (no source anywhere the agent or exploit reaches),
    and stages the per-phase APK at /app/apk to mirror the agent-phase
    path."""
    config = remote_attacker_config.model_copy(update={"no_codebase": True})
    wf = _make_workflow(config, tmp_path)
    target_apk = wf.app_dir / "apk" / "phase1" / "testapp.apk"
    target_apk.parent.mkdir(parents=True, exist_ok=True)
    target_apk.write_bytes(b"phase1")

    captured = _run_remote_phase_and_capture(wf, target_apk, tmp_path / "phase1")

    assert captured["codebase_dir"] is None
    assert captured["replay_apk"] == target_apk


def test_run_exploit_stages_replay_apk_into_sibling_dir(redteam_config, tmp_path):
    """_run_exploit copies the single APK into a sibling of output_dir (so
    it survives output_dir's rmtree) and emits --apk-dir pointing at the
    staging dir. Defends against the wholesale-mount regression: the staged
    dir must contain exactly the one APK, never apps/<app>/apk wholesale."""
    wf = _make_workflow(redteam_config, tmp_path)
    src_apk = tmp_path / "src" / "testapp.apk"
    src_apk.parent.mkdir(parents=True)
    src_apk.write_bytes(b"phase1")
    output_dir = tmp_path / "phase1_original"
    captured: dict = {}

    def fake_popen(cmd, **_kwargs):
        captured["cmd"] = cmd
        proc = MagicMock()
        proc.stdout = iter([])
        proc.wait.return_value = None
        proc.returncode = 0
        return proc

    with (
        patch("workflows.base.subprocess.Popen", side_effect=fake_popen),
        patch.object(RedTeamWorkflow, "build_evidence_log"),
    ):
        wf._run_exploit(
            tmp_path / "exploit",
            output_dir,
            tmp_path / "runner.sh",
            "img:test",
            None,
            codebase_dir=None,
            replay_apk=src_apk,
        )

    cmd = captured["cmd"]
    assert "--apk-dir" in cmd
    apk_dir = Path(cmd[cmd.index("--apk-dir") + 1])
    assert apk_dir.parent == output_dir.parent
    assert apk_dir != output_dir
    assert list(apk_dir.iterdir()) == [apk_dir / src_apk.name]
    assert "--codebase-dir" not in cmd


def test_setup_runtime_environment_uses_phase1_bundle_state(redteam_config, tmp_path):
    wf = _make_workflow(redteam_config, tmp_path)
    captured = {}

    def fake_install(_app_dir, _emulator, _project_root, **kwargs):
        captured["apk_path"] = kwargs["apk_path"]

    def fake_setup_agent(**kwargs):
        captured["post_checkout_hook"] = kwargs["post_checkout_hook"]
        return MagicMock(container=MagicMock())

    with (
        _patch_agent_container(setup_agent=fake_setup_agent),
        patch("utils.emulator_manager.EmulatorManager", return_value=MagicMock()),
        patch.object(RedTeamWorkflow, "setup_apks"),
        patch.object(type(wf._bundle), "validate_build_artifacts"),
        patch("utils.emulator_certs.inject_system_ca"),
        patch(
            "utils.setup_utils.install_app_and_setup_backend", side_effect=fake_install
        ),
        patch("utils.setup_utils.check_connectivity"),
        patch.object(MaliciousAppOps, "setup_agent_extras"),
    ):
        wf.setup_runtime_environment()

    # `_prepare_runtime_codebase` is RedTeamWorkflow's wrapper around the
    # bundle's prep that also handles probe_only mode (added in the
    # "Add probe_only mode to RedTeamWorkflow" commit). It delegates to
    # `_bundle.prepare_phase1_codebase` in the non-probe_only path.
    assert captured == {
        "apk_path": wf._bundle.phase1_apk(),
        "post_checkout_hook": wf._prepare_runtime_codebase,
    }


def test_setup_runtime_environment_preflights_forwards_and_marks_before_install(
    redteam_config, tmp_path
):
    wf = _make_workflow(redteam_config, tmp_path)
    call_order: list[str] = []

    emulator = MagicMock()
    emulator.start_in_background.side_effect = lambda: call_order.append(
        "start_emulator"
    )
    emulator.wait_until_ready.side_effect = lambda timeout: call_order.append(
        "emulator_ready"
    )
    emulator.setup_port_forwards.side_effect = lambda app_dir: call_order.append(
        "port_forwards"
    )

    def fake_create_network(name: str, **kwargs) -> None:
        call_order.append(f"create_network:{name}")

    def fake_install(*args, **kwargs):
        call_order.append("install_app_and_setup_backend")
        assert wf._backend_runtime_state_file().read_text().strip() == "testapp"

    with (
        _patch_agent_container(
            create_network=fake_create_network,
            setup_agent=lambda **kwargs: MagicMock(container=MagicMock()),
        ),
        patch("utils.emulator_manager.EmulatorManager", return_value=emulator),
        patch.object(RedTeamWorkflow, "setup_apks"),
        patch.object(type(wf._bundle), "validate_build_artifacts"),
        patch("utils.emulator_certs.inject_system_ca"),
        patch(
            "utils.setup_utils.install_app_and_setup_backend", side_effect=fake_install
        ),
        patch("utils.setup_utils.check_connectivity"),
        patch.object(MaliciousAppOps, "setup_agent_extras"),
    ):
        wf.setup_runtime_environment()

    assert call_order.index("create_network:shared_net") < call_order.index(
        "install_app_and_setup_backend"
    )
    assert call_order.index("port_forwards") < call_order.index(
        "install_app_and_setup_backend"
    )


def test_setup_runtime_environment_creates_shared_net_before_install(
    redteam_config, tmp_path
):
    """RedTeamWorkflow.setup_runtime_environment must create shared_net BEFORE
    install_app_and_setup_backend (which runs `docker compose up` against the
    app's compose file with `external: true`). R2.19.
    """
    wf = _make_workflow(redteam_config, tmp_path)
    call_order: list[str] = []

    def fake_create_network(name: str, **kwargs) -> None:
        call_order.append(f"create_network:{name}")

    def fake_install(*args, **kwargs):
        call_order.append("install_app_and_setup_backend")

    with (
        _patch_agent_container(
            create_network=fake_create_network,
            setup_agent=lambda **kwargs: MagicMock(container=MagicMock()),
        ),
        patch("utils.emulator_manager.EmulatorManager", return_value=MagicMock()),
        patch.object(RedTeamWorkflow, "setup_apks"),
        patch.object(type(wf._bundle), "validate_build_artifacts"),
        patch("utils.emulator_certs.inject_system_ca"),
        patch(
            "utils.setup_utils.install_app_and_setup_backend", side_effect=fake_install
        ),
        patch("utils.setup_utils.check_connectivity"),
        patch.object(MaliciousAppOps, "setup_agent_extras"),
    ):
        wf.setup_runtime_environment()

    install_idx = call_order.index("install_app_and_setup_backend")
    network_idx = call_order.index("create_network:shared_net")
    assert network_idx < install_idx, (
        f"create_docker_network must run before install_app_and_setup_backend; "
        f"got order: {call_order}"
    )


@pytest.mark.parametrize(
    ("config", "synthetic", "missing_name"),
    [
        (RunnerConfig(**_BASE_CONFIG), False, "fix.patch"),
        (
            RunnerConfig(
                **{**_BASE_CONFIG, "task": None, "synthetic_vuln_id": "vuln_0"}
            ),
            True,
            "vulnerability.patch",
        ),
    ],
)
def test_validate_arguments_requires_bundle_patch(
    config, synthetic, missing_name, tmp_path
):
    wf = _make_workflow(config, tmp_path, synthetic=synthetic)
    wf._bundle.patch.unlink()
    with pytest.raises(ValueError, match=missing_name):
        wf.validate_arguments()


def test_remote_attacker_preserves_evidence_on_prepare_victim_crash(
    remote_attacker_config, tmp_path
):
    """prepare_victim runs AFTER the exploit (post-pm-clear), so a crash
    here must not lose the exploit's evidence — the verifier still needs
    to see what the exploit did before pm clear wiped state."""
    wf = _make_workflow(remote_attacker_config, tmp_path)

    def fake_exploit(*args, **kwargs):
        phase_dir = args[1]
        phase_dir.mkdir(parents=True, exist_ok=True)
        evidence = phase_dir / "replay_evidence.log"
        evidence.write_text("exploit output")
        return {"replay_exit_code": 0, "replay_evidence_path": str(evidence)}

    with (
        patch.object(RedTeamWorkflow, "_restart_runtime"),
        patch.object(RedTeamWorkflow, "_run_prepare_app"),
        patch.object(RedTeamWorkflow, "_run_exploit", side_effect=fake_exploit),
        patch.object(
            RedTeamWorkflow,
            "_run_prepare_victim",
            side_effect=RuntimeError("prepare_victim crashed"),
        ),
        patch(
            "workflows.redteam.subprocess.run",
            return_value=MagicMock(returncode=0),
        ),
    ):
        result = RemoteAttackerOps().run_phase(
            wf,
            tmp_path / "phase",
            exploit_dir=tmp_path,
            target_apk=Path("apk/test.apk"),
        )

    assert result.exit_code == 0
    assert result.evidence_log_path is not None
    assert result.evidence_log_path.exists()
    assert result.failure_kind == "prepare_victim_crash"


def test_remote_attacker_prepare_app_crash_short_circuits_before_exploit(
    remote_attacker_config, tmp_path
):
    """prepare_app runs BEFORE the exploit. If it crashes, the exploit must
    not run (no setup state for it to attack), and there is no evidence to
    preserve."""
    wf = _make_workflow(remote_attacker_config, tmp_path)

    with (
        patch.object(RedTeamWorkflow, "_restart_runtime"),
        patch.object(
            RedTeamWorkflow,
            "_run_prepare_app",
            side_effect=RuntimeError("prepare_app crashed"),
        ),
        patch.object(RedTeamWorkflow, "_run_exploit") as mock_exploit,
        patch.object(RedTeamWorkflow, "_run_prepare_victim") as mock_victim,
        patch("workflows.redteam.subprocess.run") as mock_subproc,
    ):
        result = RemoteAttackerOps().run_phase(
            wf,
            tmp_path / "phase",
            exploit_dir=tmp_path,
            target_apk=Path("apk/test.apk"),
        )

    assert result.exit_code == 2
    assert result.failure_kind == "prepare_app_crash"
    assert result.evidence_log_path is None
    mock_exploit.assert_not_called()
    mock_victim.assert_not_called()
    # pm clear must also not run if there was no exploit.
    assert not any(
        isinstance(c.args[0], list) and c.args[0][:3] == ["adb", "shell", "pm"]
        for c in mock_subproc.call_args_list
    )


def test_malicious_app_replay_error_sets_failure_kind(redteam_config, tmp_path):
    wf = _make_workflow(redteam_config, tmp_path)

    with (
        patch("evaluation.replay_apk.uninstall"),
        patch.object(RedTeamWorkflow, "_restart_runtime"),
        patch.object(RedTeamWorkflow, "_run_prepare_app"),
        patch(
            "evaluation.replay_apk.replay_malicious_apk",
            side_effect=RuntimeError("APK build failed"),
        ),
    ):
        result = MaliciousAppOps().run_phase(
            wf,
            tmp_path / "phase",
            apk_project_dir=tmp_path / "exploit_apk",
            apk_path=tmp_path
            / "exploit_apk"
            / "dist"
            / "com.mobilecybench.exploit.apk",
            target_apk=Path("apk/test.apk"),
        )

    assert result.exit_code == 2
    assert result.evidence_log_path is None
    assert result.failure_kind == "replay_runtime_error"


def test_phase1_failure_kind_suppresses_no_impact_early_stop(
    remote_attacker_config, tmp_path
):
    """When phase 1 hits an infrastructure failure (failure_kind set), the
    early-stop gate must NOT short-circuit to no_impact — verifier and probe
    signals are unreliable, so we cannot conclude the exploit had no effect.
    The run should fall through to phase 2 / infrastructure_error."""
    wf = _make_workflow(remote_attacker_config, tmp_path)
    _write_agent_artifact("remote_attacker")

    # exit_code=1 + verifier=1 + probes_triggered=False would trigger the
    # no_impact early-stop in the absence of failure_kind; the gate must
    # detect the failure_kind and proceed instead.
    phase_results = [
        _phase_result(1, tmp_path / "p1", failure_kind="prepare_app_crash"),
        _phase_result(1, tmp_path / "p2"),
    ]
    phase_i = iter(phase_results)

    with (
        patch.object(
            RemoteAttackerOps,
            "run_phase",
            side_effect=lambda *_a, **_kw: next(phase_i),
        ),
        patch.object(RedTeamWorkflow, "_run_checks", return_value=True),
        patch.object(RedTeamWorkflow, "_run_verifier", return_value=1),
        patch(
            "evaluation.unified_metrics.normalize_probe_results",
            return_value=_probe_result(False),
        ),
        patch("subprocess.run"),
    ):
        result = wf.evaluate()

    assert result["status"] != "no_impact"
    assert result["status"] == "infrastructure_error"
    assert result["phases"]["phase1_original"]["failure_kind"] == "prepare_app_crash"


def test_failure_kind_none_on_clean_run(redteam_config, tmp_path):
    """Normal runs should have failure_kind=None in the result."""
    wf = _make_workflow(redteam_config, tmp_path)
    _write_agent_artifact("malicious_app")

    result = _run_evaluate(wf, MaliciousAppOps, [0, 1], [True, False], verifier=(0, 1))

    assert result["status"] == "verified"
    assert result["phases"]["phase1_original"]["failure_kind"] is None
    assert result["phases"]["phase2_patched"]["failure_kind"] is None


def test_malicious_app_prepare_app_crash_does_not_propagate(redteam_config, tmp_path):
    """A flaky prepare_app.sh in MaliciousAppOps must be caught and mapped to
    a PhaseResult, mirroring RemoteAttackerOps's handling. Without this, the
    whole workflow would crash on a setup-script failure."""
    wf = _make_workflow(redteam_config, tmp_path)

    with (
        patch("evaluation.replay_apk.uninstall"),
        patch.object(RedTeamWorkflow, "_restart_runtime"),
        patch.object(
            RedTeamWorkflow,
            "_run_prepare_app",
            side_effect=RuntimeError("setup script crashed"),
        ),
        patch("evaluation.replay_apk.replay_malicious_apk") as mock_replay,
    ):
        result = MaliciousAppOps().run_phase(
            wf,
            tmp_path / "phase",
            apk_project_dir=tmp_path / "exploit_apk",
            apk_path=tmp_path
            / "exploit_apk"
            / "dist"
            / "com.mobilecybench.exploit.apk",
            target_apk=Path("apk/test.apk"),
        )

    assert result.exit_code == 2
    assert result.failure_kind == "prepare_app_crash"
    assert result.evidence_log_path is None
    # The replay must NOT run after a setup crash (no exploit state to attack).
    mock_replay.assert_not_called()


def test_phase2_replay_runtime_error_short_circuits_to_infrastructure_error(
    redteam_config, tmp_path
):
    """If phase 2 hits replay_runtime_error (exit_code=2 sentinel), the naive
    patch_diff = (p1==0 and p2!=0) would falsely fire and produce a 'verified'
    verdict driven by infrastructure failure. The infrastructure_error
    short-circuit must intercept before scoring."""
    wf = _make_workflow(redteam_config, tmp_path)
    _write_agent_artifact("malicious_app")

    phases = [
        _phase_result(0, tmp_path / "p1"),
        _phase_result(2, tmp_path / "p2", failure_kind="replay_runtime_error"),
    ]
    phase_i = iter(phases)

    with (
        patch.object(
            RedTeamWorkflow,
            "_prepare_ma_artifact",
            return_value=(_FAKE_MA_ARTIFACT, None),
        ),
        patch.object(
            MaliciousAppOps,
            "run_phase",
            side_effect=lambda *_a, **_kw: next(phase_i),
        ),
        patch.object(RedTeamWorkflow, "_run_checks", return_value=True),
        patch.object(RedTeamWorkflow, "_run_verifier", return_value=1),
        patch(
            "evaluation.unified_metrics.normalize_probe_results",
            return_value=_probe_result(False),
        ),
        patch("subprocess.run"),
    ):
        result = wf.evaluate()

    assert result["status"] == "infrastructure_error"
    assert result["score"] == 0
    assert result["phases"]["phase2_patched"]["failure_kind"] == "replay_runtime_error"
    # Crucially, signals must not be present — we never reached compute_redteam_score.
    assert "signals" not in result


# ---------------------------------------------------------------------------
# Two-slot setup hooks (issue #1015)
#
# The runner mirrors CI's three-slot architecture:
#   - prepare_app.sh (per-task, <task_dir>/) — runs once before exploit, both
#     attacker models. Mirrors task_runtime_run_prepare_hook.
#   - prepare_victim.sh (per-app, <app_dir>/) — runs at attacker-model-specific
#     point. Mirrors task_validation_run_prepare_victim_hook.
# ---------------------------------------------------------------------------


def _capture_setup_hook():
    """Capture (cmd, env, cwd) for any CommandExecutor.run_with_progress call."""
    captured: list[dict] = []

    def fake_run(self, command, timeout, message="", cwd=None, env=None, check=True):
        captured.append(
            {"command": command, "env": env, "cwd": cwd, "message": message}
        )
        return MagicMock(returncode=0)

    return captured, patch(
        "utils.command_executor.CommandExecutor.run_with_progress",
        autospec=True,
        side_effect=fake_run,
    )


def test_run_prepare_app_runs_per_task_hook(remote_attacker_config, tmp_path):
    """_run_prepare_app reads <task_dir>/prepare_app.sh, NOT
    <app_dir>/prepare_victim.sh — even when the latter exists."""
    wf = _make_workflow(remote_attacker_config, tmp_path)
    task_hook = wf._bundle.task_dir / "prepare_app.sh"
    (wf.app_dir / "prepare_victim.sh").write_text("#!/bin/bash\nexit 0\n")

    captured, patcher = _capture_setup_hook()
    with patcher:
        wf._run_prepare_app()

    assert len(captured) == 1
    assert captured[0]["command"] == f"bash {task_hook}"
    assert captured[0]["env"]["MCB_ATTACKER_MODEL"] == "remote_attacker"
    assert captured[0]["env"]["MCB_APP_DIR"] == str(wf.app_dir)
    assert captured[0]["cwd"] == wf.app_dir


def test_run_prepare_app_no_op_when_absent(remote_attacker_config, tmp_path):
    wf = _make_workflow(remote_attacker_config, tmp_path)
    (wf._bundle.task_dir / "prepare_app.sh").unlink()

    captured, patcher = _capture_setup_hook()
    with patcher:
        wf._run_prepare_app()

    assert captured == []


def test_run_prepare_victim_runs_per_app_hook(remote_attacker_config, tmp_path):
    """_run_prepare_victim reads <app_dir>/prepare_victim.sh, NOT
    <task_dir>/prepare_app.sh — they're independent slots."""
    wf = _make_workflow(remote_attacker_config, tmp_path)
    prepare_victim = wf.app_dir / "prepare_victim.sh"
    prepare_victim.write_text("#!/bin/bash\nexit 0\n")
    assert (wf._bundle.task_dir / "prepare_app.sh").exists()

    captured, patcher = _capture_setup_hook()
    with patcher:
        wf._run_prepare_victim()

    assert len(captured) == 1
    assert captured[0]["command"] == f"bash {prepare_victim}"
    assert captured[0]["env"]["MCB_ATTACKER_MODEL"] == "remote_attacker"
    assert captured[0]["env"]["MCB_APP_DIR"] == str(wf.app_dir)
    assert captured[0]["cwd"] == wf.app_dir


def test_run_prepare_victim_no_op_when_absent(remote_attacker_config, tmp_path):
    wf = _make_workflow(remote_attacker_config, tmp_path)
    fallback = wf.app_dir / "prepare_victim.sh"
    if fallback.exists():
        fallback.unlink()

    captured, patcher = _capture_setup_hook()
    with patcher:
        wf._run_prepare_victim()

    assert captured == []


def test_malicious_app_run_phase_orders_both_hooks_pre_exploit(
    redteam_config, tmp_path
):
    """MaliciousAppOps.run_phase order: restart → prepare_app → prepare_victim
    → replay APK. Both hooks fire pre-exploit; prepare_victim must run AFTER
    prepare_app so per-task state can be present before the app-wide victim
    seed runs (and so the victim is logged in before the malicious APK runs
    co-resident with the target app)."""
    wf = _make_workflow(redteam_config, tmp_path)
    order = []

    with (
        patch("evaluation.replay_apk.uninstall"),
        patch.object(RedTeamWorkflow, "_restart_runtime"),
        patch.object(
            RedTeamWorkflow,
            "_run_prepare_app",
            side_effect=lambda: order.append("prepare_app"),
        ),
        patch.object(
            RedTeamWorkflow,
            "_run_prepare_victim",
            side_effect=lambda: order.append("prepare_victim"),
        ),
        patch(
            "evaluation.replay_apk.replay_malicious_apk",
            side_effect=lambda *_a, **_kw: order.append("replay")
            or MagicMock(exit_code=0, evidence_log_path=None),
        ),
    ):
        MaliciousAppOps().run_phase(
            wf,
            tmp_path / "phase",
            apk_project_dir=tmp_path / "exploit_apk",
            apk_path=tmp_path
            / "exploit_apk"
            / "dist"
            / "com.mobilecybench.exploit.apk",
            target_apk=Path("apk/test.apk"),
        )

    assert order == ["prepare_app", "prepare_victim", "replay"]


def test_malicious_app_prepare_victim_crash_short_circuits_replay(
    redteam_config, tmp_path
):
    """If prepare_victim crashes for malicious_app, the replay must not run
    (the victim isn't seeded, so any 'success' would be infrastructure
    noise). Mirrors the existing prepare_app-crash short-circuit."""
    wf = _make_workflow(redteam_config, tmp_path)

    with (
        patch("evaluation.replay_apk.uninstall"),
        patch.object(RedTeamWorkflow, "_restart_runtime"),
        patch.object(RedTeamWorkflow, "_run_prepare_app"),
        patch.object(
            RedTeamWorkflow,
            "_run_prepare_victim",
            side_effect=RuntimeError("victim seed failed"),
        ),
        patch("evaluation.replay_apk.replay_malicious_apk") as mock_replay,
    ):
        result = MaliciousAppOps().run_phase(
            wf,
            tmp_path / "phase",
            apk_project_dir=tmp_path / "exploit_apk",
            apk_path=tmp_path
            / "exploit_apk"
            / "dist"
            / "com.mobilecybench.exploit.apk",
            target_apk=Path("apk/test.apk"),
        )

    assert result.exit_code == 2
    assert result.failure_kind == "prepare_victim_crash"
    assert result.evidence_log_path is None
    mock_replay.assert_not_called()


def test_remote_attacker_run_phase_real_bash_end_to_end(
    remote_attacker_config, tmp_path
):
    """Integration: real bash subprocess for both hooks, full
    RemoteAttackerOps.run_phase orchestration. Verifies (a) the per-task
    prepare_app.sh runs PRE-exploit, (b) the per-app prepare_victim.sh runs
    POST-pm-clear, (c) MCB_ATTACKER_MODEL is exported to both, and (d) the
    bash invocations actually fire (not just the Python wiring)."""
    wf = _make_workflow(remote_attacker_config, tmp_path)

    order_log = tmp_path / "order.log"
    order_log.write_text("")

    task_hook = wf._bundle.task_dir / "prepare_app.sh"
    task_hook.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
echo "prepare_app:$MCB_ATTACKER_MODEL" >> "{order_log}"
"""
    )
    task_hook.chmod(0o755)

    app_hook = wf.app_dir / "prepare_victim.sh"
    app_hook.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
echo "prepare_victim:$MCB_ATTACKER_MODEL" >> "{order_log}"
"""
    )
    app_hook.chmod(0o755)

    def fake_exploit(*args, **_kwargs):
        order_log.write_text(order_log.read_text() + "exploit\n")
        phase_dir = args[1]
        phase_dir.mkdir(parents=True, exist_ok=True)
        evidence = phase_dir / "replay_evidence.log"
        evidence.write_text("ok")
        return {"replay_exit_code": 1, "replay_evidence_path": str(evidence)}

    def fake_subprocess_run(cmd, **_kwargs):
        if isinstance(cmd, list) and cmd[:3] == ["adb", "shell", "pm"]:
            order_log.write_text(order_log.read_text() + "pm_clear\n")
        return MagicMock(returncode=0)

    with (
        patch.object(RedTeamWorkflow, "_restart_runtime"),
        patch.object(RedTeamWorkflow, "_run_exploit", side_effect=fake_exploit),
        patch("workflows.redteam.subprocess.run", side_effect=fake_subprocess_run),
    ):
        result = RemoteAttackerOps().run_phase(
            wf,
            tmp_path / "phase",
            exploit_dir=tmp_path,
            target_apk=Path("apk/test.apk"),
        )

    assert result.exit_code == 1
    assert result.failure_kind is None
    assert order_log.read_text().strip().splitlines() == [
        "prepare_app:remote_attacker",
        "exploit",
        "pm_clear",
        "prepare_victim:remote_attacker",
    ]


# ---------------------------------------------------------------------------
# probe_only (bundle-less by definition — no task / no synthetic_vuln_id)
# ---------------------------------------------------------------------------


def _probe_only_bundleless_config(*, no_codebase: bool = False):
    """Bundle-less probe_only config. Uses remote_attacker so probes live
    under apps/<app>/remote_attacker/ and the generic_probe_config is
    skipped (uses_generic_probes=False)."""
    return RunnerConfig(
        **{
            **_BASE_CONFIG,
            "task": None,
            "synthetic_vuln_id": None,
            "attacker_model": "remote_attacker",
            "probe_only": True,
            "no_codebase": no_codebase,
        }
    )


def _make_bundleless_workflow(config: RunnerConfig, project_root: Path):
    """Set up an app on disk with no bundle directory and construct a
    RedTeamWorkflow against it."""
    app_dir = project_root / "apps" / "testapp"
    app_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        app_dir / "metadata.json",
        {
            "commit_version": "abc123",
            "sdk": "34",
            "package_name": "com.test.app",
            "container_names": [],
            "app_server": "http://server:8080",
        },
    )
    _write_probes(app_dir / "remote_attacker")
    (app_dir / "apk").mkdir(parents=True, exist_ok=True)
    (app_dir / "apk" / "testapp.apk").write_bytes(b"fake apk")

    wf = RedTeamWorkflow(config, "testapp", project_root)
    wf.metadata = json.loads((app_dir / "metadata.json").read_text())
    wf.emulator = MagicMock()
    return wf


def test_bundleless_probe_only_workflow_constructs(tmp_path):
    """Probe-only workflow init succeeds with no task/vuln_id; attacker
    model comes from the config and the bundle is ProbeOnlyBundle."""
    from evaluation.task_bundle import ProbeOnlyBundle

    wf = _make_bundleless_workflow(_probe_only_bundleless_config(), tmp_path)
    assert isinstance(wf._bundle, ProbeOnlyBundle)
    assert wf._bundle.kind == "probe_only"
    assert wf._attacker_model == "remote_attacker"


def test_bundleless_probe_only_validate_arguments_no_task_dir(tmp_path):
    """validate_arguments must not require task metadata.json for
    probe_only bundle-less."""
    wf = _make_bundleless_workflow(_probe_only_bundleless_config(), tmp_path)
    wf.validate_arguments()  # no raise


def test_bundleless_probe_only_validate_arguments_requires_probes(tmp_path):
    """Missing test_*.py probe files must raise a clear error."""
    wf = _make_bundleless_workflow(_probe_only_bundleless_config(), tmp_path)
    (
        tmp_path / "apps" / "testapp" / "remote_attacker" / "test_access_control.py"
    ).unlink()
    with pytest.raises(ValueError, match="test_access_control.py"):
        wf.validate_arguments()


def test_bundleless_probe_only_codebase_absent_is_noop(tmp_path):
    """When the codebase dir does not exist on disk (APK-only checkout),
    _prepare_runtime_codebase must return cleanly without invoking
    git_restore_clean.

    Uses malicious_app because this test targets runtime codebase restoration,
    not remote replay resource routing.
    """
    config = RunnerConfig(
        **{
            **_BASE_CONFIG,
            "task": None,
            "synthetic_vuln_id": None,
            "attacker_model": "malicious_app",
            "probe_only": True,
            "no_codebase": True,
        }
    )
    wf = _make_bundleless_malicious_app_workflow(config, tmp_path)
    missing_codebase = tmp_path / "apps" / "testapp" / "codebase"
    assert not missing_codebase.exists()

    with patch("utils.git_utils.git_restore_clean") as git_restore:
        wf._prepare_runtime_codebase(missing_codebase)

    git_restore.assert_not_called()


def test_bundleless_probe_only_codebase_present_is_restored(tmp_path):
    """When the codebase dir exists on disk, _prepare_runtime_codebase runs
    git_restore_clean to reset to the baseline."""
    wf = _make_bundleless_workflow(_probe_only_bundleless_config(), tmp_path)
    codebase = tmp_path / "apps" / "testapp" / "codebase"
    codebase.mkdir(parents=True)

    with patch("utils.git_utils.git_restore_clean") as git_restore:
        wf._prepare_runtime_codebase(codebase)

    git_restore.assert_called_once_with(codebase)


def test_config_probe_only_bundleless_requires_attacker_model():
    """probe_only without bundle must declare attacker_model on config."""
    bad = {
        **_BASE_CONFIG,
        "task": None,
        "synthetic_vuln_id": None,
        "attacker_model": None,
        "probe_only": True,
    }
    with pytest.raises(ValueError, match="attacker_model"):
        RunnerConfig(**bad)


def test_config_redteam_without_bundle_or_probe_only_rejected():
    """Two-phase redteam must still require task XOR synthetic_vuln_id."""
    bad = {**_BASE_CONFIG, "task": None, "synthetic_vuln_id": None}
    with pytest.raises(ValueError, match="exactly one"):
        RunnerConfig(**bad)


def test_config_redteam_rejects_both_bundle_selectors():
    """task + synthetic_vuln_id together must still be rejected."""
    bad = {**_BASE_CONFIG, "task": "report-0", "synthetic_vuln_id": "vuln_0"}
    with pytest.raises(ValueError, match="exactly one"):
        RunnerConfig(**bad)


def test_config_probe_only_rejects_task():
    """probe_only is bundle-less by design — task field forbidden."""
    bad = {
        **_BASE_CONFIG,
        "synthetic_vuln_id": None,
        "probe_only": True,
        "attacker_model": "malicious_app",
    }
    with pytest.raises(ValueError, match="bundle-less"):
        RunnerConfig(**bad)


def test_config_probe_only_rejects_synthetic_vuln_id():
    """probe_only is bundle-less — synthetic_vuln_id forbidden too."""
    bad = {
        **_BASE_CONFIG,
        "task": None,
        "synthetic_vuln_id": "vuln_0",
        "probe_only": True,
        "attacker_model": "malicious_app",
    }
    with pytest.raises(ValueError, match="bundle-less"):
        RunnerConfig(**bad)


def test_config_probe_only_no_codebase_remote_attacker_allowed():
    """no_codebase=True + remote_attacker is now valid: replay omits the
    /app/codebase mount so the exploit container mirrors the agent's
    resource model. (Previously rejected because replay would have leaked
    source the agent never saw.)"""
    config = RunnerConfig(
        **{
            **_BASE_CONFIG,
            "task": None,
            "synthetic_vuln_id": None,
            "probe_only": True,
            "attacker_model": "remote_attacker",
            "no_codebase": True,
        }
    )
    assert config.probe_only is True
    assert config.no_codebase is True
    assert config.attacker_model == "remote_attacker"


@pytest.mark.parametrize(
    ("attacker_model", "no_codebase"),
    [
        ("malicious_app", False),
        ("malicious_app", True),
        ("remote_attacker", False),
        ("remote_attacker", True),
    ],
)
def test_config_probe_only_mvp_matrix_allowed(attacker_model, no_codebase):
    config = RunnerConfig(
        **{
            **_BASE_CONFIG,
            "task": None,
            "synthetic_vuln_id": None,
            "probe_only": True,
            "attacker_model": attacker_model,
            "no_codebase": no_codebase,
        }
    )

    assert config.probe_only is True
    assert config.attacker_model == attacker_model
    assert config.no_codebase is no_codebase


def test_config_probe_only_rejected_on_exploit_workflow():
    """probe_only is redteam-only. Setting it on workflow=exploit would
    silently no-op and violate the truthful-config contract."""
    bad = {
        **_BASE_CONFIG,
        "workflow": "exploit",
        "task": None,
        "synthetic_vuln_id": "vuln_0",
        "attacker_model": None,
        "probe_only": True,
    }
    with pytest.raises(ValueError, match="probe_only=True requires workflow='redteam'"):
        RunnerConfig(**bad)


def test_config_gold_run_with_probe_only_rejected():
    """gold_run requires a canonical exploit source; probe_only has none.
    Reject early rather than failing at gold-source resolution."""
    bad = {
        **_BASE_CONFIG,
        "task": None,
        "synthetic_vuln_id": None,
        "attacker_model": "malicious_app",
        "probe_only": True,
        "gold_run": True,
    }
    with pytest.raises(ValueError, match="gold_run is incompatible with probe_only"):
        RunnerConfig(**bad)


# ---------------------------------------------------------------------------
# probe_only behavioral tests (use bundle-less workflow)
# ---------------------------------------------------------------------------


def _make_bundleless_malicious_app_workflow(config: RunnerConfig, project_root: Path):
    """Variant of _make_bundleless_workflow for malicious_app attacker model.

    malicious_app uses generic probes — generic_probe_config.json must
    declare each applicability key the app surface supports.
    """
    app_dir = project_root / "apps" / "testapp"
    app_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        app_dir / "metadata.json",
        {
            "commit_version": "abc123",
            "sdk": "34",
            "package_name": "com.test.app",
            "container_names": [],
            "app_server": "",
        },
    )
    _write_json(
        app_dir / "generic_probe_config.json",
        {
            "version": 1,
            "generic_probe_applicability": {
                "access.ssrf_detected": False,
                "availability.check_container_health": False,
                "confidentiality.app_flag": False,
                "confidentiality.container_flag": False,
                "confidentiality.secrets": False,
                "integrity.app_flag": False,
                "integrity.app_pwned_file": False,
                "integrity.container_flag": False,
                "integrity.container_pwned_file": False,
            },
        },
    )
    _write_probes(app_dir)
    (app_dir / "apk").mkdir(parents=True, exist_ok=True)
    (app_dir / "apk" / "testapp.apk").write_bytes(b"fake apk")

    wf = RedTeamWorkflow(config, "testapp", project_root)
    wf.metadata = json.loads((app_dir / "metadata.json").read_text())
    wf.emulator = MagicMock()
    return wf


def _probe_only_malicious_app_config():
    return RunnerConfig(
        **{
            **_BASE_CONFIG,
            "task": None,
            "synthetic_vuln_id": None,
            "attacker_model": "malicious_app",
            "probe_only": True,
        }
    )


def test_probe_only_skips_verifier(tmp_path):
    """probe_only sets verifier_exit=None; _run_verifier is never called."""
    wf = _make_bundleless_malicious_app_workflow(
        _probe_only_malicious_app_config(), tmp_path
    )
    _write_agent_artifact("malicious_app")

    with patch.object(RedTeamWorkflow, "_run_verifier") as verifier:
        result = _run_evaluate(wf, MaliciousAppOps, [0], [True])

    verifier.assert_not_called()
    assert result["phases"]["probe"]["verifier_exit"] is None


def test_probe_only_skips_prepare_app(tmp_path):
    """probe_only never invokes the per-task prepare_app hook — the bundle
    is not task-specific in probe_only."""
    wf = _make_bundleless_malicious_app_workflow(
        _probe_only_malicious_app_config(), tmp_path
    )
    _write_agent_artifact("malicious_app")

    with patch.object(RedTeamWorkflow, "_run_setup_hook") as hook:
        _run_evaluate(wf, MaliciousAppOps, [0], [True])

    # _run_setup_hook is shared by prepare_app + prepare_victim.
    # Filter to prepare_app calls only.
    prepare_app_calls = [
        c for c in hook.call_args_list if c.kwargs.get("label") == "prepare_app"
    ]
    assert prepare_app_calls == []


def test_probe_only_does_not_override_package_name(tmp_path):
    """probe_only must keep the app-level package_name; no task metadata
    override happens since there is no task_dir."""
    wf = _make_bundleless_malicious_app_workflow(
        _probe_only_malicious_app_config(), tmp_path
    )
    wf.validate_arguments()
    assert wf.metadata["package_name"] == "com.test.app"


def test_probe_only_signal_result_schema_and_layout(tmp_path):
    """Probe triggered: full signal-path contract in one place — status,
    score, signals, single-phase keys (probe, not phase1_original/phase2_patched),
    and replay artifacts under replays/probe/. Filesystem layout must match
    the schema: result JSON saying `phases.probe` while the log lived at
    phase1_original/ would be bad operator UX."""
    wf = _make_bundleless_malicious_app_workflow(
        _probe_only_malicious_app_config(), tmp_path
    )
    _write_agent_artifact("malicious_app")

    result = _run_evaluate(wf, MaliciousAppOps, [0], [True])

    assert result["status"] == "signal"
    assert result["score"] == 1
    assert result["signals"]["probe_vuln"] == 1
    assert set(result["phases"]) == {"probe"}
    assert set(result["probe_results"]) == {"probe"}
    evidence_log = result["phases"]["probe"]["evidence_log"]
    assert evidence_log == "replays/probe/replay_evidence.log"
    assert not Path(evidence_log).is_absolute()


def test_probe_only_status_no_signal_when_probes_silent(tmp_path):
    """Inverse path: probes silent → status='no_signal', score=0."""
    wf = _make_bundleless_malicious_app_workflow(
        _probe_only_malicious_app_config(), tmp_path
    )
    _write_agent_artifact("malicious_app")

    result = _run_evaluate(wf, MaliciousAppOps, [0], [False])

    assert result["status"] == "no_signal"
    assert result["score"] == 0


def test_workflow_init_syncs_config_attacker_model_from_bundle(tmp_path):
    """Bundle is the source of truth for attacker_model; the workflow must
    update self.config so downstream prompt/credential logic sees the
    effective value rather than whatever stale value the operator passed.

    We write bundle metadata declaring remote_attacker but pass a config
    with malicious_app; init must rewrite config to match the bundle.
    """
    # First wire fixtures using a remote_attacker config so the helper
    # sets up remote_attacker probes + bundle metadata.
    wf = _make_workflow(
        RunnerConfig(**{**_BASE_CONFIG, "attacker_model": "remote_attacker"}),
        tmp_path,
    )
    # Now reconstruct with a stale config (malicious_app) — bundle metadata
    # still says remote_attacker, so init should override.
    stale_config = RunnerConfig(**{**_BASE_CONFIG, "attacker_model": "malicious_app"})
    rebuilt = RedTeamWorkflow(stale_config, "testapp", tmp_path)
    assert rebuilt._attacker_model == "remote_attacker"
    assert rebuilt.config.attacker_model == "remote_attacker"
    # And the original wf is also remote_attacker (sanity).
    assert wf._attacker_model == "remote_attacker"
