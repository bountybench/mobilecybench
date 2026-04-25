import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from models.config import RunnerConfig
from utils.logger import logger_manager
from workflows.redteam import (
    MaliciousAppOps,
    PhaseResult,
    RedTeamWorkflow,
    RemoteAttackerOps,
)

_BASE_CONFIG = {
    "build_type": "skip-apk",
    "model": "test",
    "agent_image": "test:latest",
    "server_access": True,
    "adb_access": "full",
    "max_iterations": 10,
    "max_model_response_tokens": 1000,
    "screenshot_mode": False,
    "dry_run": False,
    "emulator_backend": "native",
    "emulator_display": "headed",
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
        "combined": {"triggered": triggered},
        "app_specific_triggered": triggered,
        "generic_triggered": triggered,
    }


def _phase_result(exit_code: int, phase_dir: Path) -> PhaseResult:
    phase_dir.mkdir(parents=True, exist_ok=True)
    evidence = phase_dir / "replay_evidence.log"
    evidence.write_text(str(exit_code))
    return PhaseResult(exit_code=exit_code, evidence_log_path=evidence)


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


def _run_evaluate(wf, ops_cls, exits, probes, *, verifier=(1, 1)):
    phase_i = iter(exits)
    probe_i = iter(probes)
    verifier_i = iter(verifier)

    with (
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


def test_phase1_probe_parse_failure_is_not_no_impact(redteam_config, tmp_path):
    wf = _make_workflow(redteam_config, tmp_path)
    _write_agent_artifact("malicious_app")

    with (
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
        patch.object(MaliciousAppOps, "run_phase", side_effect=fail_on_second_run),
        patch.object(RedTeamWorkflow, "_run_checks", return_value=True),
        patch.object(RedTeamWorkflow, "_run_verifier", return_value=1),
        patch(
            "evaluation.unified_metrics.normalize_probe_results",
            return_value=_probe_result(True),
        ),
        patch("subprocess.run") as mock_run,
    ):
        with pytest.raises(RuntimeError, match="phase 2 infra crash"):
            wf.evaluate()

    restore_calls = [call.args[0] for call in mock_run.call_args_list if call.args]
    assert restore_calls.count(["git", "checkout", "--", "."]) == 3


def test_remote_attacker_run_phase_orders_steps(remote_attacker_config, tmp_path):
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
    assert order == ["exploit", "pm_clear", "prepare_app"]


def test_setup_runtime_environment_uses_phase1_bundle_state(redteam_config, tmp_path):
    wf = _make_workflow(redteam_config, tmp_path)
    captured = {}

    def fake_install(_app_dir, _emulator, _project_root, **kwargs):
        captured["apk_path"] = kwargs["apk_path"]

    def fake_setup_agent(**kwargs):
        captured["post_checkout_hook"] = kwargs["post_checkout_hook"]
        return MagicMock(container=MagicMock())

    with (
        patch("utils.emulator_manager.EmulatorManager", return_value=MagicMock()),
        patch.object(RedTeamWorkflow, "setup_apks"),
        patch.object(type(wf._bundle), "validate_build_artifacts"),
        patch("utils.emulator_certs.inject_system_ca"),
        patch(
            "utils.setup_utils.install_app_and_setup_backend", side_effect=fake_install
        ),
        patch(
            "agent.agent_container.setup_agent_environment",
            side_effect=fake_setup_agent,
        ),
        patch("utils.setup_utils.check_connectivity"),
        patch.object(MaliciousAppOps, "setup_agent_extras"),
    ):
        wf.setup_runtime_environment()

    assert captured == {
        "apk_path": wf._bundle.phase1_apk(),
        "post_checkout_hook": wf._bundle.prepare_phase1_codebase,
    }


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
