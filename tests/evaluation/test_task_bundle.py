"""Unit tests for evaluation.task_bundle."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluation.task_bundle import (
    ProbeOnlyBundle,
    SyntheticBundle,
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
            SyntheticBundle(app_dir=Path("/root/apps/myapp"), vuln_id="vuln_0"),
            Path("/root/apps/myapp/synthetic_vulnerabilities/vuln_0"),
            Path("/root/apps/myapp/apk/vuln_0/myapp.apk"),
            Path("/root/apps/myapp/apk/myapp.apk"),
        ),
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
        (_config(synthetic_vuln_id="vuln_0"), SyntheticBundle),
        (_config(task="report-1"), ZerodayBundle),
    ],
)
def test_resolve_bundle_selects_expected_kind(cfg, expected_type):
    bundle = resolve_bundle(cfg, Path("/p"), "app")
    assert isinstance(bundle, expected_type)


def test_resolve_bundle_preserves_synthetic_vuln_id():
    bundle = resolve_bundle(_config(synthetic_vuln_id="vuln_0"), Path("/p"), "app")
    assert isinstance(bundle, SyntheticBundle)
    assert bundle.vuln_id == "vuln_0"


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
    "cfg",
    [
        _config(),
        _config(task="r1", synthetic_vuln_id="v0"),
        _config(task="", synthetic_vuln_id=""),
    ],
)
def test_resolve_bundle_rejects_invalid_selector(cfg):
    with pytest.raises(ValueError, match="exactly one"):
        resolve_bundle(cfg, Path("/p"), "app")


@pytest.mark.parametrize(
    ("bundle_factory", "prepare", "expected"),
    [
        (
            lambda repo: SyntheticBundle(app_dir=repo, vuln_id="v"),
            "prepare_phase1_codebase",
            "vulnerable\n",
        ),
        (
            lambda repo: SyntheticBundle(app_dir=repo, vuln_id="v"),
            "prepare_phase2_codebase",
            "clean\n",
        ),
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


def test_synthetic_validate_build_artifacts_requires_both_apks(tmp_path):
    bundle = SyntheticBundle(app_dir=tmp_path, vuln_id="vuln_0")
    with pytest.raises(FileNotFoundError):
        bundle.validate_build_artifacts(tmp_path)

    (tmp_path / "apk" / "vuln_0").mkdir(parents=True)
    (tmp_path / "apk" / "vuln_0" / f"{tmp_path.name}.apk").touch()
    (tmp_path / "apk" / f"{tmp_path.name}.apk").touch()
    bundle.validate_build_artifacts(tmp_path)


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


def test_build_task_runtime_env_synthetic_uses_vuln_id_as_task_id(tmp_path):
    """SyntheticBundle has no .task but exposes .vuln_id; the env should
    populate MCB_TASK_ID from it so synthetic prepare_app hooks can resolve
    their per-vuln directory."""
    app_dir = _seed_app(tmp_path)
    vuln_dir = app_dir / "synthetic_vulnerabilities" / "vuln_0"
    vuln_dir.mkdir(parents=True)
    (vuln_dir / "metadata.json").write_text(
        json.dumps({"attacker_model": "remote_attacker"})
    )
    (vuln_dir / "vulnerability.patch").write_text("--- a\n+++ b\n")
    bundle = SyntheticBundle(app_dir=app_dir, vuln_id="vuln_0")

    env = build_task_runtime_env(
        bundle=bundle, app_dir=app_dir, attacker_model="remote_attacker"
    )

    assert env["MCB_TASK_ID"] == "vuln_0"
    assert env["MCB_TASK_DIR"] == str(vuln_dir)
    assert env["MCB_TASK_METADATA_JSON"] == str(vuln_dir / "metadata.json")
    assert env["MCB_FIX_PATCH"].endswith("vulnerability.patch")


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
