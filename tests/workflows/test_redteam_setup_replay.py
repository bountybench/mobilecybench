"""Tests for replay-mode gating in RedTeamWorkflow.setup_runtime_environment.

Bug context: prior to this gating, setup_runtime_environment unconditionally
invoked setup_agent_environment(agent_image=...), which pulled the agent
Docker image even when replay_exploit_dir was set and the agent loop would
never run. On hosts without the configured tag cached locally and with the
tag absent from the registry, this aborted the replay before the emulator
booted.
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from models.config import RunnerConfig
from workflows.redteam import (
    MaliciousAppOps,
    RedTeamWorkflow,
    _phase_slug_for_output_dir,
)

_BASE_CONFIG = {
    "workflow": "redteam",
    "probe_only": True,
    "attacker_model": "malicious_app",
    "task": None,
    "synthetic_vuln_id": None,
    "build_type": "skip-apk",
    "model": "test",
    "agent_image": "cybench/mobilecybench:does-not-exist",
    "max_iterations": 10,
    "max_model_response_tokens": 1000,
    "dry_run": False,
    "emulator_backend": "native",
    "emulator_display": "headless",
    "network_mode": "permissive",
}


def _task_dir(project_root: Path) -> Path:
    return project_root / "apps" / "demoapp" / "zero_day_vulnerabilities" / "report-0"


def _make_workflow(tmp_path: Path, replay_dir: Path | None) -> RedTeamWorkflow:
    cfg = {**_BASE_CONFIG}
    if replay_dir is not None:
        cfg["replay_exploit_dir"] = str(replay_dir)
    config = RunnerConfig(**cfg)
    workflow = RedTeamWorkflow.__new__(RedTeamWorkflow)
    workflow.config = config
    workflow.app_name = "moememos"
    workflow.app_dir = tmp_path / "apps" / "moememos"
    workflow.app_dir.mkdir(parents=True, exist_ok=True)
    workflow.project_root = tmp_path
    workflow.metadata = {"sdk": "35", "app_server": "memos-server"}
    workflow.agent_env = None
    workflow._ops = MaliciousAppOps()
    workflow._bundle = MagicMock()
    workflow.setup_apks = MagicMock()
    workflow._preflight_cleanup_app_runtime = MagicMock()
    workflow._mark_app_backend_active = MagicMock()
    workflow._runtime_apk = MagicMock(return_value=tmp_path / "victim.apk")
    (tmp_path / "victim.apk").write_bytes(b"")
    workflow._prepare_runtime_codebase = MagicMock()
    workflow._run_agent_login = MagicMock()
    workflow._inject_apk_template = MagicMock()
    return workflow


def _patch_runtime_deps():
    return [
        patch("utils.setup_utils.check_connectivity"),
        patch("utils.setup_utils.install_app_and_setup_backend"),
        patch("utils.emulator_certs.inject_system_ca"),
        patch("utils.emulator_manager.EmulatorManager"),
        patch("agent.runtime.container.setup_agent_environment"),
    ]


def test_replay_exploit_dir_skips_agent_container_setup(tmp_path):
    """When replay_exploit_dir is set, agent container init must be skipped."""
    replay_dir = tmp_path / "agent_exploit"
    (replay_dir / "exploit_apk").mkdir(parents=True)
    workflow = _make_workflow(tmp_path, replay_dir=replay_dir)

    patches = _patch_runtime_deps()
    started = [p.start() for p in patches]
    try:
        (
            check_conn,
            install_app,
            inject_ca,
            EmulatorManager,
            setup_agent_env,
        ) = started
        EmulatorManager.return_value = MagicMock()

        workflow.setup_runtime_environment()

        # The whole point: agent docker image is never touched in replay mode.
        setup_agent_env.assert_not_called()
        check_conn.assert_not_called()
        workflow._run_agent_login.assert_not_called()
        assert workflow.agent_env is None
    finally:
        for p in patches:
            p.stop()


def test_non_replay_path_still_calls_agent_setup(tmp_path):
    """Sanity check: non-replay runs still invoke the agent container setup."""
    workflow = _make_workflow(tmp_path, replay_dir=None)

    patches = _patch_runtime_deps()
    started = [p.start() for p in patches]
    try:
        (
            check_conn,
            install_app,
            inject_ca,
            EmulatorManager,
            setup_agent_env,
        ) = started
        EmulatorManager.return_value = MagicMock()
        agent_env = MagicMock()
        setup_agent_env.return_value = agent_env

        workflow.setup_runtime_environment()

        setup_agent_env.assert_called_once()
        assert workflow.agent_env is agent_env
        workflow._run_agent_login.assert_called_once()
    finally:
        for p in patches:
            p.stop()


def test_prepare_app_and_verifier_share_per_phase_output_dir(tmp_path):
    """Regression: a real prepare_app.sh writes a marker to
    ``$MCB_OUTPUT_DIR/foo`` and the subsequent verifier (which reads
    ``MCB_OUTPUT_DIR`` from the same per-phase replay dir) must see it.

    Guards against the failure mode where ``_run_setup_hook`` exports
    ``MCB_OUTPUT_DIR=logger_manager.get_logs_dir()`` while
    ``_run_verifier`` reads from the per-phase ``replay_dir`` — hook
    would write a marker the verifier never finds. The fix routes the
    per-phase ``phase_dir`` through ``_run_setup_hook`` so both paths
    agree on a single per-phase directory.
    """
    import json

    from evaluation.task_bundle import ZerodayBundle

    # Layout: real apps/<app>/metadata.json + real task dir with
    # prepare_app.sh and a verify-equivalent reader stub so we can
    # exercise the end-to-end env contract without spinning up an
    # emulator.
    app_dir = tmp_path / "apps" / "demoapp"
    app_dir.mkdir(parents=True)
    (app_dir / "metadata.json").write_text(
        json.dumps({"package_name": "io.demo", "commit_version": "abc123"})
    )

    task_dir = _task_dir(tmp_path)
    task_dir.mkdir(parents=True)
    (task_dir / "metadata.json").write_text(
        json.dumps({"attacker_model": "malicious_app"})
    )
    (task_dir / "fix.patch").write_text("--- a\n+++ b\n")

    # Real hook script that writes to $MCB_OUTPUT_DIR/foo (mirrors the
    # OwnTracks phase_offset.txt handoff pattern).
    prepare_app = task_dir / "prepare_app.sh"
    prepare_app.write_text(
        '#!/usr/bin/env bash\nset -euo pipefail\necho marker > "$MCB_OUTPUT_DIR/foo"\n'
    )
    prepare_app.chmod(0o755)

    bundle = ZerodayBundle(project_root=tmp_path, app_name="demoapp", task="report-0")

    workflow = RedTeamWorkflow.__new__(RedTeamWorkflow)
    workflow.config = RunnerConfig(
        workflow="redteam",
        probe_only=False,
        attacker_model="malicious_app",
        task="report-0",
        synthetic_vuln_id=None,
        build_type="skip-apk",
        model="test",
        agent_image="cybench/mobilecybench:does-not-exist",
        max_iterations=10,
        max_model_response_tokens=1000,
        dry_run=False,
        emulator_backend="native",
        emulator_display="headless",
        network_mode="permissive",
    )
    workflow.app_dir = app_dir
    workflow.project_root = tmp_path
    workflow._bundle = bundle
    workflow._attacker_model = "malicious_app"

    phase_dir = tmp_path / "logs" / "experiment" / "replays" / "phase1_original"
    phase_dir.mkdir(parents=True)

    # Run the actual hook through _run_setup_hook (per-phase context).
    workflow._run_setup_hook(hook=prepare_app, label="prepare_app", phase_dir=phase_dir)

    # Hook wrote `foo` under MCB_OUTPUT_DIR. The verifier (modeled after
    # RedTeamWorkflow._run_verifier) sets MCB_OUTPUT_DIR=phase_dir and
    # looks for the same marker. Both paths must resolve to phase_dir.
    marker = phase_dir / "foo"
    assert marker.exists(), (
        f"prepare_app marker missing at {marker}; "
        f"MCB_OUTPUT_DIR drifted from phase_dir"
    )

    # Mirror _run_verifier's env: MCB_APP_DIR + MCB_OUTPUT_DIR=phase_dir,
    # then run a dummy verifier that reads $MCB_OUTPUT_DIR/foo. If the
    # plumbing is consistent the file is found; otherwise it isn't.
    verifier = task_dir / "verify_files" / "verify_exploit.sh"
    verifier.parent.mkdir(parents=True, exist_ok=True)
    verifier.write_text(
        '#!/usr/bin/env bash\nset -e\ntest -f "$MCB_OUTPUT_DIR/foo" && echo OK || (echo MISSING; exit 1)\n'
    )
    verifier.chmod(0o755)

    # Drive the actual `_run_verifier` so the test catches regressions in
    # its env construction (not just the contract). Verifier exit 0 iff
    # the marker is at MCB_OUTPUT_DIR — i.e. `_run_verifier` resolved
    # MCB_OUTPUT_DIR to the same per-phase dir as `_run_setup_hook`.
    verify_phase_dir = tmp_path / "logs" / "experiment" / "replays" / "verify_phase1"
    verify_phase_dir.mkdir(parents=True, exist_ok=True)
    exit_code = workflow._run_verifier(verify_phase_dir, replay_dir=phase_dir)
    assert exit_code == 0, (
        f"_run_verifier did not find marker; "
        f"log={(verify_phase_dir / 'verify_exploit.log').read_text()!r}"
    )


def test_run_verifier_exports_full_task_runtime_env(tmp_path):
    """`_run_verifier` must export the same ``MCB_*`` contract as the
    setup hooks (``build_task_runtime_env``). Regression for the original
    partial-env version that set only ``MCB_APP_DIR`` and ``MCB_OUTPUT_DIR``
    — hooks moved to the validator contract (e.g. ``MCB_PACKAGE_NAME``,
    ``MCB_TASK_DIR``, ``MCB_TASK_METADATA_JSON``) would silently fail
    inside the verifier even though prepare_app saw them."""
    import json

    from evaluation.task_bundle import ZerodayBundle, build_task_runtime_env

    app_dir = tmp_path / "apps" / "demoapp"
    app_dir.mkdir(parents=True)
    (app_dir / "metadata.json").write_text(
        json.dumps({"package_name": "io.demo", "commit_version": "abc123"})
    )

    task_dir = _task_dir(tmp_path)
    task_dir.mkdir(parents=True)
    (task_dir / "metadata.json").write_text(json.dumps({"task_id": "report-0"}))
    (task_dir / "fix.patch").write_text("--- a\n+++ b\n")
    verifier = task_dir / "verify_files" / "verify_exploit.sh"
    verifier.parent.mkdir(parents=True, exist_ok=True)
    verifier.write_text("#!/usr/bin/env bash\nexit 0\n")
    verifier.chmod(0o755)

    workflow = RedTeamWorkflow.__new__(RedTeamWorkflow)
    workflow.config = RunnerConfig(
        workflow="redteam",
        probe_only=False,
        attacker_model="remote_attacker",
        task="report-0",
        synthetic_vuln_id=None,
        build_type="skip-apk",
        model="test",
        agent_image="cybench/mobilecybench:does-not-exist",
        max_iterations=10,
        max_model_response_tokens=1000,
        dry_run=False,
        emulator_backend="native",
        emulator_display="headless",
        network_mode="permissive",
    )
    workflow.app_dir = app_dir
    workflow.project_root = tmp_path
    workflow._bundle = ZerodayBundle(
        project_root=tmp_path, app_name="demoapp", task="report-0"
    )
    workflow._attacker_model = "remote_attacker"

    verify_phase_dir = tmp_path / "verify_phase1_original"
    replay_dir = tmp_path / "replays" / "phase1_original"
    replay_dir.mkdir(parents=True)

    captured = {}
    real_run = subprocess.run

    def capture(cmd, *args, **kwargs):
        captured["env"] = kwargs.get("env")
        captured["cwd"] = kwargs.get("cwd")
        return real_run(cmd, *args, **kwargs)

    with patch("workflows.redteam.subprocess.run", side_effect=capture):
        workflow._run_verifier(verify_phase_dir, replay_dir=replay_dir)

    expected = build_task_runtime_env(
        bundle=workflow._bundle,
        app_dir=app_dir,
        attacker_model="remote_attacker",
        output_dir=replay_dir,
        phase="vulnerable",
    )
    # The verifier env must be a superset of the contract — every key the
    # validator would export under task_runtime_set_context is present, and
    # carries the same value.
    for key, value in expected.items():
        assert captured["env"].get(key) == value, (
            f"_run_verifier dropped {key}={value!r} "
            f"(saw {captured['env'].get(key)!r})"
        )
    # Validator parity: task_runtime_run_verifier cds to the task_dir
    # before invoking verify_exploit.sh (scripts/task_runtime_common.sh:255).
    assert captured["cwd"] == workflow._bundle.task_dir


def test_run_verifier_omits_phase_when_replay_dir_is_none(tmp_path):
    """If the replay never produced an evidence path (e.g. crash before
    replay), `_run_verifier` is called with ``replay_dir=None``. It must
    skip ``MCB_OUTPUT_DIR`` and ``MCB_PHASE`` rather than exporting stale
    values, and the verifier must still run (validator parity for hooks
    with no per-phase scope)."""
    import json

    from evaluation.task_bundle import ZerodayBundle

    app_dir = tmp_path / "apps" / "demoapp"
    app_dir.mkdir(parents=True)
    (app_dir / "metadata.json").write_text(json.dumps({"package_name": "io.demo"}))

    task_dir = _task_dir(tmp_path)
    task_dir.mkdir(parents=True)
    (task_dir / "metadata.json").write_text(json.dumps({"task_id": "report-0"}))
    verifier = task_dir / "verify_files" / "verify_exploit.sh"
    verifier.parent.mkdir(parents=True, exist_ok=True)
    verifier.write_text("#!/usr/bin/env bash\nexit 0\n")
    verifier.chmod(0o755)

    workflow = RedTeamWorkflow.__new__(RedTeamWorkflow)
    workflow.config = RunnerConfig(
        workflow="redteam",
        probe_only=False,
        attacker_model="remote_attacker",
        task="report-0",
        synthetic_vuln_id=None,
        build_type="skip-apk",
        model="test",
        agent_image="cybench/mobilecybench:does-not-exist",
        max_iterations=10,
        max_model_response_tokens=1000,
        dry_run=False,
        emulator_backend="native",
        emulator_display="headless",
        network_mode="permissive",
    )
    workflow.app_dir = app_dir
    workflow.project_root = tmp_path
    workflow._bundle = ZerodayBundle(
        project_root=tmp_path, app_name="demoapp", task="report-0"
    )
    workflow._attacker_model = "remote_attacker"

    captured = {}
    real_run = subprocess.run

    def capture(cmd, *args, **kwargs):
        captured["env"] = kwargs.get("env")
        return real_run(cmd, *args, **kwargs)

    with patch("workflows.redteam.subprocess.run", side_effect=capture):
        exit_code = workflow._run_verifier(tmp_path / "verify_dir", replay_dir=None)

    assert exit_code == 0
    assert "MCB_OUTPUT_DIR" not in captured["env"]
    assert "MCB_PHASE" not in captured["env"]
    # Bundle-derived fields still appear (no per-phase scope needed).
    assert captured["env"].get("MCB_TASK_DIR") == str(task_dir)


def test_phase_slug_for_output_dir_maps_runner_dirs_to_validator_slugs(tmp_path):
    """Lock the runner→validator slug mapping. Audiobookshelf prepare_app
    hooks branch on ``MCB_PHASE=vulnerable``; if the helper returns
    "phase1" the hook silently skips on every phase. Mirrors
    ``scripts/zero_day_task_common.sh`` (``task_validation_run_phase
    "vulnerable" / "secure"``)."""
    assert _phase_slug_for_output_dir(tmp_path / "phase1_original") == "vulnerable"
    assert _phase_slug_for_output_dir(tmp_path / "phase2_patched") == "secure"
    # Probe-only and unrecognized names degrade to None (no MCB_PHASE).
    assert _phase_slug_for_output_dir(tmp_path / "probe") is None
    assert _phase_slug_for_output_dir(None) is None


def test_run_prepare_victim_exports_per_phase_context(tmp_path):
    """Validator parity: prepare_victim runs under the same
    ``task_runtime_set_context`` as prepare_app and the verifier — so
    victim hooks see the per-phase ``MCB_OUTPUT_DIR`` / ``MCB_PHASE``.
    Without this routing, victim hooks that write under
    ``$MCB_OUTPUT_DIR`` write to ``logs/`` and the verifier never sees
    the state."""
    import json

    from evaluation.task_bundle import ZerodayBundle

    app_dir = tmp_path / "apps" / "demoapp"
    app_dir.mkdir(parents=True)
    (app_dir / "metadata.json").write_text(json.dumps({"package_name": "io.demo"}))

    task_dir = _task_dir(tmp_path)
    task_dir.mkdir(parents=True)
    (task_dir / "metadata.json").write_text(json.dumps({"task_id": "report-0"}))

    # Real prepare_victim.sh that asserts validator-equivalent env.
    prepare_victim = app_dir / "prepare_victim.sh"
    prepare_victim.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        '[ "$MCB_PHASE" = vulnerable ] || { echo wrong-phase:$MCB_PHASE; exit 1; }\n'
        'echo seeded > "$MCB_OUTPUT_DIR/victim_seed"\n'
    )
    prepare_victim.chmod(0o755)

    workflow = RedTeamWorkflow.__new__(RedTeamWorkflow)
    workflow.config = RunnerConfig(
        workflow="redteam",
        probe_only=False,
        attacker_model="malicious_app",
        task="report-0",
        synthetic_vuln_id=None,
        build_type="skip-apk",
        model="test",
        agent_image="cybench/mobilecybench:does-not-exist",
        max_iterations=10,
        max_model_response_tokens=1000,
        dry_run=False,
        emulator_backend="native",
        emulator_display="headless",
        network_mode="permissive",
    )
    workflow.app_dir = app_dir
    workflow.project_root = tmp_path
    workflow._bundle = ZerodayBundle(
        project_root=tmp_path, app_name="demoapp", task="report-0"
    )
    workflow._attacker_model = "malicious_app"

    # phase_dir is intentionally NOT pre-mkdir'd; _run_setup_hook must
    # create it before invoking the hook (validator parity:
    # task_validation_run_phase does ``mkdir -p "$phase_output"``
    # before task_runtime_set_context). Without this, the hook's
    # ``echo seeded > "$MCB_OUTPUT_DIR/victim_seed"`` fails on the very
    # first phase before _run_exploit creates the dir.
    phase_dir = tmp_path / "logs" / "exp" / "replays" / "phase1_original"
    workflow._run_prepare_victim(phase_dir=phase_dir)

    assert (phase_dir / "victim_seed").read_text().strip() == "seeded"
