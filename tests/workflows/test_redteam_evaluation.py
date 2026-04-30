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


def _phase_result(exit_code: int, phase_dir: Path, failure_kind=None) -> PhaseResult:
    phase_dir.mkdir(parents=True, exist_ok=True)
    evidence = phase_dir / "replay_evidence.log"
    evidence.write_text(str(exit_code))
    return PhaseResult(
        exit_code=exit_code, evidence_log_path=evidence, failure_kind=failure_kind
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


def test_setup_runtime_environment_uses_phase1_bundle_state(redteam_config, tmp_path):
    wf = _make_workflow(redteam_config, tmp_path)
    captured = {}

    def fake_install(_app_dir, _emulator, _project_root, **kwargs):
        captured["apk_path"] = kwargs["apk_path"]

    def fake_setup_agent(**kwargs):
        captured["post_checkout_hook"] = kwargs["post_checkout_hook"]
        return MagicMock(container=MagicMock())

    with (
        patch("agent.agent_container.create_docker_network"),
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


def test_setup_runtime_environment_creates_shared_net_before_install(
    redteam_config, tmp_path
):
    """RedTeamWorkflow.setup_runtime_environment must create shared_net BEFORE
    install_app_and_setup_backend (which runs `docker compose up` against the
    app's compose file with `external: true`). R2.19.
    """
    wf = _make_workflow(redteam_config, tmp_path)
    call_order: list[str] = []

    def fake_create_network(name: str) -> None:
        call_order.append(f"create_network:{name}")

    def fake_install(*args, **kwargs):
        call_order.append("install_app_and_setup_backend")

    with (
        patch(
            "agent.agent_container.create_docker_network",
            side_effect=fake_create_network,
        ),
        patch("utils.emulator_manager.EmulatorManager", return_value=MagicMock()),
        patch.object(RedTeamWorkflow, "setup_apks"),
        patch.object(type(wf._bundle), "validate_build_artifacts"),
        patch("utils.emulator_certs.inject_system_ca"),
        patch(
            "utils.setup_utils.install_app_and_setup_backend", side_effect=fake_install
        ),
        patch(
            "agent.agent_container.setup_agent_environment",
            return_value=MagicMock(container=MagicMock()),
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


# =============================================================================
# probe_only mode — no task, no patch, no verifier; score on probe activity
# =============================================================================


_PROBE_ONLY_CONFIG = {
    **_BASE_CONFIG,
    "task": None,
    "synthetic_vuln_id": None,
    "probe_only": True,
}


def _make_probe_only_workflow(config, project_root):
    """Workflow fixture without any task/patch/verifier files on disk."""
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
    (app_dir / "codebase").mkdir(exist_ok=True)
    if config.attacker_model == "malicious_app":
        _write_json(
            app_dir / "generic_probe_config.json",
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
            },
        )
        _write_probes(app_dir)
    else:
        _write_probes(app_dir / "remote_attacker")
    wf = RedTeamWorkflow(config, "testapp", project_root)
    wf.metadata = json.loads((app_dir / "metadata.json").read_text())
    wf.emulator = MagicMock()
    return wf


def test_probe_only_config_rejects_task_or_vuln_id():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="mutually exclusive"):
        RunnerConfig(**{**_PROBE_ONLY_CONFIG, "task": "report-1"})
    with pytest.raises(ValidationError, match="mutually exclusive"):
        RunnerConfig(**{**_PROBE_ONLY_CONFIG, "synthetic_vuln_id": "vuln_0"})


def test_probe_only_config_requires_attacker_model():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="attacker_model"):
        RunnerConfig(**{**_PROBE_ONLY_CONFIG, "attacker_model": None})


def test_probe_only_config_rejects_with_exploit_workflow():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="workflow='redteam'"):
        RunnerConfig(
            **{
                **_PROBE_ONLY_CONFIG,
                "workflow": "exploit",
                "attacker_model": None,
                "synthetic_vuln_id": "vuln_0",
            }
        )


def test_probe_only_validate_arguments_ignores_missing_task_files(tmp_path):
    """probe_only must not check for task patch / verify_files / metadata."""
    config = RunnerConfig(**_PROBE_ONLY_CONFIG)
    wf = _make_probe_only_workflow(config, tmp_path)
    # No zerodays/ tree, no synthetic_vulnerabilities/ tree — must not raise.
    wf.validate_arguments()


def test_probe_only_short_circuits_to_vulnerable_when_probes_trigger(tmp_path):
    config = RunnerConfig(**_PROBE_ONLY_CONFIG)
    wf = _make_probe_only_workflow(config, tmp_path)
    _write_agent_artifact("malicious_app")

    with (
        patch.object(
            MaliciousAppOps,
            "run_phase",
            side_effect=lambda *_a, **_kw: _phase_result(0, _a[1]),
        ),
        patch.object(RedTeamWorkflow, "_run_checks", return_value=True),
        patch.object(RedTeamWorkflow, "_run_verifier") as mock_verifier,
        patch(
            "evaluation.unified_metrics.normalize_probe_results",
            return_value=_probe_result(True),
        ),
        patch("subprocess.run"),
    ):
        result = wf.evaluate()

    assert result["status"] == "vulnerable"
    assert result["score"] == 1
    assert result["signals"] == {"probe_vuln": 1}
    # Verifier must NEVER run in probe_only.
    mock_verifier.assert_not_called()
    # No phase2 in result — short-circuited.
    assert set(result["phases"].keys()) == {"phase1_original"}


def test_probe_only_no_signal_when_probes_quiet(tmp_path):
    config = RunnerConfig(**_PROBE_ONLY_CONFIG)
    wf = _make_probe_only_workflow(config, tmp_path)
    _write_agent_artifact("malicious_app")

    with (
        patch.object(
            MaliciousAppOps,
            "run_phase",
            side_effect=lambda *_a, **_kw: _phase_result(0, _a[1]),
        ),
        patch.object(RedTeamWorkflow, "_run_checks", return_value=True),
        patch.object(RedTeamWorkflow, "_run_verifier"),
        patch(
            "evaluation.unified_metrics.normalize_probe_results",
            return_value=_probe_result(False),
        ),
        patch("subprocess.run"),
    ):
        result = wf.evaluate()

    assert result["status"] == "no_signal"
    assert result["score"] == 0


def test_probe_only_skips_prepare_app_hook(tmp_path):
    """No task → no per-task prepare_app.sh; the hook must be a no-op."""
    config = RunnerConfig(**_PROBE_ONLY_CONFIG)
    wf = _make_probe_only_workflow(config, tmp_path)
    with patch.object(RedTeamWorkflow, "_run_setup_hook") as mock_hook:
        wf._run_prepare_app()
    mock_hook.assert_not_called()
