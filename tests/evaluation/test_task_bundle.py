"""Unit tests for evaluation.task_bundle."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluation.task_bundle import (
    SyntheticBundle,
    TaskBundle,
    ZerodayBundle,
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
    getattr(bundle, prepare)(repo)
    assert (repo / "hello.txt").read_text() == expected


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
