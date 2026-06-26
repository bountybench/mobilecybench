"""Unit tests for evaluation.task_bundle."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluation.task_bundle import (
    ProbeOnlyBundle,
    TaskBundle,
    ZerodayBundle,
    assert_zerodays_initialized,
    build_task_runtime_env,
    resolve_bundle,
)


def _config(**kwargs):
    values = {"task": None, "synthetic_vuln_id": None}
    values.update(kwargs)
    return SimpleNamespace(**values)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True)


@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "hello.txt").write_text("clean\n")
    _git(repo, "add", "hello.txt")
    _git(repo, "commit", "-m", "init", "-q")

    patch = tmp_path / "change.patch"
    patch.write_text(
        "diff --git a/hello.txt b/hello.txt\n"
        "--- a/hello.txt\n"
        "+++ b/hello.txt\n"
        "@@ -1 +1 @@\n"
        "-clean\n"
        "+vulnerable\n"
    )
    return repo, patch


@pytest.mark.parametrize(
    ("bundle", "task_dir", "phase1_apk", "phase2_apk"),
    [
        (
            ZerodayBundle(
                project_root=Path("/root"), app_name="myapp", task="report-1"
            ),
            Path("/root/zerodays/reports/myapp/report-1/task"),
            Path("/root/apps/myapp/apk/myapp.apk"),
            Path(
                "/root/zerodays/reports/myapp/report-1/artifacts/hardened_apk/myapp.apk"
            ),
        ),
    ],
)
def test_bundle_paths(bundle, task_dir, phase1_apk, phase2_apk):
    assert isinstance(bundle, TaskBundle)
    assert bundle.task_dir == task_dir
    assert bundle.exploit_dir == task_dir / "exploit_files"
    assert bundle.phase1_apk() == phase1_apk
    assert bundle.phase2_apk() == phase2_apk


def _initialized_zerodays_root(tmp_path: Path) -> Path:
    """Project root with a non-empty zerodays/ submodule directory."""
    (tmp_path / "zerodays").mkdir()
    (tmp_path / "zerodays" / ".keep").write_text("")
    return tmp_path


@pytest.mark.parametrize(
    ("cfg", "expected_type"),
    [
        (_config(task="report-1"), ZerodayBundle),
        (_config(probe_only=True, attacker_model="malicious_app"), ProbeOnlyBundle),
    ],
)
def test_resolve_bundle_selects_expected_kind(cfg, expected_type):
    bundle = resolve_bundle(cfg, Path("/p"), "app")
    assert isinstance(bundle, expected_type)


def test_assert_zerodays_initialized_raises_when_submodule_missing(tmp_path):
    """A bare clone leaves zerodays/ empty; downstream callers should
    see an actionable error pointing at the submodule, not a generic
    path-not-found from an opener deeper in the stack."""
    with pytest.raises(
        FileNotFoundError, match="zerodays/ submodule is not initialized"
    ):
        assert_zerodays_initialized(tmp_path)


def test_assert_zerodays_initialized_passes_when_submodule_populated(tmp_path):
    """Once any content lives under zerodays/, the precondition clears."""
    assert_zerodays_initialized(_initialized_zerodays_root(tmp_path))


def test_resolve_bundle_does_not_check_filesystem(tmp_path):
    """resolve_bundle is pure path-resolution — env preconditions live
    in `assert_zerodays_initialized`, not here."""
    bundle = resolve_bundle(_config(task="report-1"), tmp_path, "app")
    assert isinstance(bundle, ZerodayBundle)


@pytest.mark.parametrize(
    ("cfg", "message"),
    [
        (_config(), "requires config.task"),
        (_config(task="r1", synthetic_vuln_id="v0"), "synthetic_vuln_id is retired"),
        (_config(synthetic_vuln_id="v0"), "synthetic_vuln_id is retired"),
        (_config(task="", synthetic_vuln_id=""), "synthetic_vuln_id is retired"),
    ],
)
def test_resolve_bundle_rejects_invalid_selector(cfg, message):
    with pytest.raises(ValueError, match=message):
        resolve_bundle(cfg, Path("/p"), "app")


@pytest.mark.parametrize(
    ("bundle_factory", "prepare", "expected"),
    [
        (
            lambda repo: ZerodayBundle(project_root=repo, app_name="x", task="t"),
            "prepare_phase1_codebase",
            "clean\n",
        ),
        (
            lambda repo: ZerodayBundle(project_root=repo, app_name="x", task="t"),
            "prepare_phase2_codebase",
            "vulnerable\n",
        ),
    ],
)
def test_phase_prep_transitions(
    git_repo, monkeypatch, bundle_factory, prepare, expected
):
    repo, patch = git_repo
    bundle = bundle_factory(repo)
    monkeypatch.setattr(type(bundle), "patch", property(lambda _: patch), raising=True)
    (repo / "hello.txt").write_text("dirty\n")
    (repo / "untracked.txt").write_text("leftover\n")
    getattr(bundle, prepare)(repo)
    assert (repo / "hello.txt").read_text() == expected
    assert not (repo / "untracked.txt").exists()


def test_zeroday_validate_build_artifacts_requires_hardened_apk(tmp_path):
    bundle = ZerodayBundle(project_root=tmp_path, app_name="x", task="t")
    (tmp_path / "apps" / "x" / "apk").mkdir(parents=True)
    (tmp_path / "apps" / "x" / "apk" / "x.apk").touch()
    with pytest.raises(FileNotFoundError, match="hardened"):
        bundle.validate_build_artifacts(tmp_path / "apps" / "x")


def test_zeroday_bundle_rejects_obfuscation_phase_mismatch(tmp_path):
    with pytest.raises(ValueError, match="not supported with zeroday tasks"):
        ZerodayBundle(
            project_root=tmp_path,
            app_name="x",
            task="t",
            runner_obfuscation="on",
        )


def test_probe_only_bundle_kind_and_apk_paths(tmp_path):
    app_dir = tmp_path / "apps" / "myapp"
    bundle = ProbeOnlyBundle(app_dir=app_dir, _attacker_model="malicious_app")
    assert bundle.kind == "probe_only"
    assert bundle.attacker_model() == "malicious_app"
    expected_apk = app_dir / "apk" / "myapp.apk"
    assert bundle.phase1_apk() == expected_apk
    assert bundle.phase2_apk() == expected_apk  # only one APK in probe_only


def test_probe_only_bundle_patch_raises():
    bundle = ProbeOnlyBundle(app_dir=Path("/tmp/x"), _attacker_model="malicious_app")
    with pytest.raises(NotImplementedError):
        _ = bundle.patch
    with pytest.raises(NotImplementedError):
        bundle.prepare_phase2_codebase(Path("/tmp/x"))


def test_probe_only_bundle_build_apks_calls_clean_baseline_build(tmp_path, monkeypatch):
    """build_type='source' must be supported: build the clean baseline APK
    once. NotImplementedError here would break source-builds for probe-only."""
    bundle = ProbeOnlyBundle(
        app_dir=tmp_path / "apps" / "myapp", _attacker_model="malicious_app"
    )
    captured = {}

    def fake_run_build(project_root, args, timeout):
        captured["project_root"] = project_root
        captured["args"] = list(args)
        captured["timeout"] = timeout

    monkeypatch.setattr("evaluation.task_bundle._run_build", fake_run_build)
    bundle.build_apks("myapp", tmp_path, timeout=600)

    assert captured == {
        "project_root": tmp_path,
        "args": ["myapp"],
        "timeout": 600,
    }


def test_probe_only_bundle_validate_build_artifacts(tmp_path):
    bundle = ProbeOnlyBundle(
        app_dir=tmp_path / "apps" / "myapp", _attacker_model="malicious_app"
    )
    with pytest.raises(FileNotFoundError, match="Probe-only APK"):
        bundle.validate_build_artifacts(tmp_path / "apps" / "myapp")
    apk = tmp_path / "apps" / "myapp" / "apk" / "myapp.apk"
    apk.parent.mkdir(parents=True)
    apk.touch()
    bundle.validate_build_artifacts(tmp_path / "apps" / "myapp")


def test_resolve_bundle_returns_probe_only_bundle(tmp_path):
    config = _config(
        probe_only=True,
        attacker_model="malicious_app",
    )
    bundle = resolve_bundle(config, tmp_path, "myapp")
    assert isinstance(bundle, ProbeOnlyBundle)
    assert bundle.attacker_model() == "malicious_app"


def test_resolve_bundle_probe_only_rejects_unknown_attacker_model(tmp_path):
    config = _config(probe_only=True, attacker_model="bogus")
    with pytest.raises(ValueError, match="attacker_model"):
        resolve_bundle(config, tmp_path, "myapp")


# ---------------------------------------------------------------------------
# build_task_runtime_env: parity with scripts/task_runtime_common.sh
# ---------------------------------------------------------------------------


def _seed_app(tmp_path: Path, *, package_name: str = "io.test", commit: str = "abc123"):
    app_dir = tmp_path / "apps" / "myapp"
    app_dir.mkdir(parents=True)
    (app_dir / "metadata.json").write_text(
        json.dumps({"package_name": package_name, "commit_version": commit})
    )
    return app_dir


def test_build_task_runtime_env_zeroday_sets_full_contract(tmp_path):
    """ZerodayBundle must export every MCB_* key that
    scripts/task_runtime_common.sh sets, matching the validator contract that
    zerodays repo PR #50+ prepare_app.sh scripts rely on.
    """
    app_dir = _seed_app(tmp_path)
    task_dir = tmp_path / "zerodays" / "reports" / "myapp" / "report-0" / "task"
    task_dir.mkdir(parents=True)
    (task_dir / "metadata.json").write_text(
        json.dumps({"attacker_model": "malicious_app"})
    )
    (task_dir / "fix.patch").write_text("--- a\n+++ b\n")
    bundle = ZerodayBundle(project_root=tmp_path, app_name="myapp", task="report-0")

    env = build_task_runtime_env(
        bundle=bundle,
        app_dir=app_dir,
        attacker_model="malicious_app",
        output_dir=tmp_path / "out",
        phase="phase1",
    )

    assert env["MCB_APP_DIR"] == str(app_dir)
    assert env["MCB_APP_METADATA_JSON"] == str(app_dir / "metadata.json")
    assert env["MCB_TASK_DIR"] == str(task_dir)
    assert env["MCB_TASK_METADATA_JSON"] == str(task_dir / "metadata.json")
    assert env["MCB_TASK_ID"] == "report-0"
    assert env["MCB_PACKAGE_NAME"] == "io.test"
    assert env["MCB_BASELINE_COMMIT"] == "abc123"
    assert env["MCB_ATTACKER_MODEL"] == "malicious_app"
    assert env["MCB_FIX_PATCH"].endswith("fix.patch")
    assert env["MCB_OUTPUT_DIR"] == str(tmp_path / "out")
    assert env["MCB_PHASE"] == "phase1"


def test_build_task_runtime_env_probe_only_omits_per_task_keys(tmp_path):
    """ProbeOnlyBundle has no task_dir/patch/task_id; per-task MCB_* keys
    must be omitted (not set to empty) so hooks can distinguish bundle-less
    invocation from a real task with missing fields."""
    app_dir = _seed_app(tmp_path)
    bundle = ProbeOnlyBundle(app_dir=app_dir, _attacker_model="malicious_app")

    env = build_task_runtime_env(
        bundle=bundle, app_dir=app_dir, attacker_model="malicious_app"
    )

    assert env["MCB_APP_DIR"] == str(app_dir)
    assert env["MCB_APP_METADATA_JSON"] == str(app_dir / "metadata.json")
    assert env["MCB_ATTACKER_MODEL"] == "malicious_app"
    for key in (
        "MCB_TASK_DIR",
        "MCB_TASK_METADATA_JSON",
        "MCB_TASK_ID",
        "MCB_FIX_PATCH",
    ):
        assert key not in env, f"{key} should be absent for ProbeOnlyBundle"


def test_build_task_runtime_env_missing_app_metadata_is_tolerated(tmp_path):
    """If apps/<app>/metadata.json is absent (e.g., minimal test fixtures),
    MCB_PACKAGE_NAME and MCB_BASELINE_COMMIT are simply omitted; the helper
    must not raise."""
    app_dir = tmp_path / "apps" / "minimal"
    app_dir.mkdir(parents=True)
    bundle = ProbeOnlyBundle(app_dir=app_dir, _attacker_model="malicious_app")

    env = build_task_runtime_env(
        bundle=bundle, app_dir=app_dir, attacker_model="malicious_app"
    )

    assert env["MCB_APP_DIR"] == str(app_dir)
    assert "MCB_APP_METADATA_JSON" not in env
    assert "MCB_PACKAGE_NAME" not in env
    assert "MCB_BASELINE_COMMIT" not in env


def test_build_task_runtime_env_sets_output_dir_and_phase(tmp_path):
    """MCB_OUTPUT_DIR and MCB_PHASE must be exported when callers supply
    them. Some prepare_app hooks (e.g., HA report-0) treat MCB_OUTPUT_DIR
    as required via bash ``: ${VAR?…}`` and fail without it."""
    app_dir = _seed_app(tmp_path)
    bundle = ProbeOnlyBundle(app_dir=app_dir, _attacker_model="malicious_app")
    output_dir = tmp_path / "logs" / "run-xyz"
    output_dir.mkdir(parents=True)

    env = build_task_runtime_env(
        bundle=bundle,
        app_dir=app_dir,
        attacker_model="malicious_app",
        output_dir=output_dir,
        phase="phase1",
    )

    assert env["MCB_OUTPUT_DIR"] == str(output_dir)
    assert env["MCB_PHASE"] == "phase1"


def test_build_task_runtime_env_task_metadata_takes_precedence(tmp_path):
    """Match scripts/zero_day_task_common.sh precedence: task metadata
    fields (task_id, runtime.package_name, app_metadata_overrides.package_name,
    baseline.commit) win over app metadata fallbacks."""
    app_dir = _seed_app(tmp_path, package_name="io.fallback", commit="appcommit")
    task_dir = tmp_path / "zerodays" / "reports" / "myapp" / "report-0" / "task"
    task_dir.mkdir(parents=True)
    (task_dir / "metadata.json").write_text(
        json.dumps(
            {
                "attacker_model": "malicious_app",
                "task_id": "report-0-overridden-id",
                "runtime": {"package_name": "io.runtime"},
                "baseline": {"commit": "taskbaseline"},
            }
        )
    )
    (task_dir / "fix.patch").write_text("--- a\n+++ b\n")
    bundle = ZerodayBundle(project_root=tmp_path, app_name="myapp", task="report-0")

    env = build_task_runtime_env(
        bundle=bundle, app_dir=app_dir, attacker_model="malicious_app"
    )

    assert env["MCB_TASK_ID"] == "report-0-overridden-id"
    assert env["MCB_PACKAGE_NAME"] == "io.runtime"
    assert env["MCB_BASELINE_COMMIT"] == "taskbaseline"


def test_build_task_runtime_env_app_metadata_overrides_section(tmp_path):
    """When task metadata has no runtime.package_name but does have
    app_metadata_overrides.package_name, the overrides section should win
    over the app metadata fallback (matches validator second-tier
    precedence)."""
    app_dir = _seed_app(tmp_path, package_name="io.fallback")
    task_dir = tmp_path / "zerodays" / "reports" / "myapp" / "report-0" / "task"
    task_dir.mkdir(parents=True)
    (task_dir / "metadata.json").write_text(
        json.dumps(
            {
                "attacker_model": "malicious_app",
                "app_metadata_overrides": {"package_name": "io.override"},
            }
        )
    )
    bundle = ZerodayBundle(project_root=tmp_path, app_name="myapp", task="report-0")

    env = build_task_runtime_env(
        bundle=bundle, app_dir=app_dir, attacker_model="malicious_app"
    )
    assert env["MCB_PACKAGE_NAME"] == "io.override"


def test_build_task_runtime_env_falls_back_to_bundle_task_id(tmp_path):
    """Without task_id/task_slug in task metadata, MCB_TASK_ID falls back
    to bundle.task — matching the validator's task-dir basename
    fallback."""
    app_dir = _seed_app(tmp_path)
    task_dir = tmp_path / "zerodays" / "reports" / "myapp" / "report-0" / "task"
    task_dir.mkdir(parents=True)
    (task_dir / "metadata.json").write_text(
        json.dumps({"attacker_model": "malicious_app"})
    )
    bundle = ZerodayBundle(project_root=tmp_path, app_name="myapp", task="report-0")

    env = build_task_runtime_env(
        bundle=bundle, app_dir=app_dir, attacker_model="malicious_app"
    )
    assert env["MCB_TASK_ID"] == "report-0"
