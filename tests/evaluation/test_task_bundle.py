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


# ---------------------------------------------------------------------------
# Path resolution — no filesystem, no git.
# ---------------------------------------------------------------------------


def test_synthetic_paths():
    bundle = SyntheticBundle(app_dir=Path("/root/apps/myapp"), vuln_id="vuln_0")
    assert bundle.kind == "synthetic"
    assert bundle.task_dir == Path(
        "/root/apps/myapp/synthetic_vulnerabilities/vuln_0"
    )
    assert bundle.exploit_dir == bundle.task_dir / "exploit_files"
    assert bundle.phase1_apk() == Path("apk/vuln_0/myapp.apk")
    assert bundle.phase2_apk() == Path("apk/myapp.apk")


def test_zeroday_paths():
    bundle = ZerodayBundle(
        project_root=Path("/root"), app_name="myapp", task="report-1"
    )
    assert bundle.kind == "zeroday"
    assert bundle.task_dir == Path("/root/zerodays/reports/myapp/report-1/task")
    assert bundle.exploit_dir == bundle.task_dir / "exploit_files"
    assert bundle.phase1_apk() == Path("apk/myapp.apk")
    # Phase 2 APK is absolute — lives outside app_dir/apk/.
    assert bundle.phase2_apk() == Path(
        "/root/zerodays/reports/myapp/report-1/artifacts/hardened_apk/myapp.apk"
    )


def test_both_implement_protocol():
    synth = SyntheticBundle(app_dir=Path("/a"), vuln_id="v")
    zero = ZerodayBundle(project_root=Path("/a"), app_name="x", task="t")
    assert isinstance(synth, TaskBundle)
    assert isinstance(zero, TaskBundle)


# ---------------------------------------------------------------------------
# resolve_bundle — XOR between synthetic_vuln_id and task.
# ---------------------------------------------------------------------------


def _config(task=None, synthetic_vuln_id=None):
    return SimpleNamespace(task=task, synthetic_vuln_id=synthetic_vuln_id)


def test_resolve_synthetic():
    bundle = resolve_bundle(_config(synthetic_vuln_id="vuln_0"), Path("/p"), "app")
    assert isinstance(bundle, SyntheticBundle)
    assert bundle.vuln_id == "vuln_0"
    assert bundle.app_dir == Path("/p/apps/app")


def test_resolve_zeroday():
    bundle = resolve_bundle(_config(task="report-1"), Path("/p"), "app")
    assert isinstance(bundle, ZerodayBundle)
    assert bundle.task == "report-1"
    assert bundle.project_root == Path("/p")


def test_resolve_rejects_both_set():
    with pytest.raises(ValueError, match="exactly one"):
        resolve_bundle(
            _config(task="r1", synthetic_vuln_id="v0"), Path("/p"), "app"
        )


def test_resolve_rejects_neither_set():
    with pytest.raises(ValueError, match="exactly one"):
        resolve_bundle(_config(), Path("/p"), "app")


def test_resolve_rejects_empty_string():
    # '' is falsy so XOR(bool("") == bool(None)) fires — should reject.
    with pytest.raises(ValueError, match="exactly one"):
        resolve_bundle(
            _config(task="", synthetic_vuln_id=""), Path("/p"), "app"
        )


# ---------------------------------------------------------------------------
# Codebase phase prep — hits git for real, in a tmp repo.
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_git_repo(tmp_path):
    """A tiny git repo with a committed hello.txt and a patch that rewrites it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
         "--allow-empty", "-m", "init", "-q"],
        cwd=repo, check=True,
    )
    (repo / "hello.txt").write_text("clean\n")
    subprocess.run(["git", "add", "hello.txt"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
         "-m", "add hello", "-q"],
        cwd=repo, check=True,
    )

    # Patch: "clean\n" → "vulnerable\n"
    patch = tmp_path / "vuln.patch"
    patch.write_text(
        "diff --git a/hello.txt b/hello.txt\n"
        "--- a/hello.txt\n"
        "+++ b/hello.txt\n"
        "@@ -1 +1 @@\n"
        "-clean\n"
        "+vulnerable\n"
    )
    return repo, patch


def test_synthetic_phase1_applies_patch(tmp_git_repo, monkeypatch):
    repo, patch = tmp_git_repo
    # SyntheticBundle looks for vulnerability.patch inside task_dir.
    # Redirect patch to our fixture patch.
    bundle = SyntheticBundle(app_dir=repo, vuln_id="v")
    monkeypatch.setattr(
        SyntheticBundle, "patch", property(lambda _: patch), raising=True
    )

    bundle.prepare_phase1_codebase(repo)
    assert (repo / "hello.txt").read_text() == "vulnerable\n"


def test_synthetic_phase2_reverts_patch(tmp_git_repo, monkeypatch):
    repo, patch = tmp_git_repo
    bundle = SyntheticBundle(app_dir=repo, vuln_id="v")
    monkeypatch.setattr(
        SyntheticBundle, "patch", property(lambda _: patch), raising=True
    )
    bundle.prepare_phase1_codebase(repo)
    assert (repo / "hello.txt").read_text() == "vulnerable\n"

    bundle.prepare_phase2_codebase(repo)
    assert (repo / "hello.txt").read_text() == "clean\n"


def test_zeroday_phase1_leaves_codebase_clean(tmp_git_repo, monkeypatch):
    repo, patch = tmp_git_repo
    bundle = ZerodayBundle(project_root=repo, app_name="x", task="t")
    monkeypatch.setattr(
        ZerodayBundle, "patch", property(lambda _: patch), raising=True
    )
    # Dirty the tree; prepare_phase1 should restore it.
    (repo / "hello.txt").write_text("dirty\n")
    bundle.prepare_phase1_codebase(repo)
    assert (repo / "hello.txt").read_text() == "clean\n"


def test_zeroday_phase2_applies_patch(tmp_git_repo, monkeypatch):
    repo, patch = tmp_git_repo
    bundle = ZerodayBundle(project_root=repo, app_name="x", task="t")
    monkeypatch.setattr(
        ZerodayBundle, "patch", property(lambda _: patch), raising=True
    )
    bundle.prepare_phase2_codebase(repo)
    assert (repo / "hello.txt").read_text() == "vulnerable\n"


# ---------------------------------------------------------------------------
# Artifact validation.
# ---------------------------------------------------------------------------


def test_synthetic_validate_missing_apk(tmp_path):
    bundle = SyntheticBundle(app_dir=tmp_path, vuln_id="vuln_0")
    with pytest.raises(FileNotFoundError):
        bundle.validate_build_artifacts(tmp_path)


def test_synthetic_validate_accepts_both_apks(tmp_path):
    bundle = SyntheticBundle(app_dir=tmp_path, vuln_id="vuln_0")
    (tmp_path / "apk" / "vuln_0").mkdir(parents=True)
    (tmp_path / "apk" / "vuln_0" / f"{tmp_path.name}.apk").touch()
    (tmp_path / "apk" / f"{tmp_path.name}.apk").touch()
    bundle.validate_build_artifacts(tmp_path)  # does not raise


def test_zeroday_validate_missing_hardened(tmp_path):
    bundle = ZerodayBundle(project_root=tmp_path, app_name="x", task="t")
    (tmp_path / "apps" / "x" / "apk").mkdir(parents=True)
    (tmp_path / "apps" / "x" / "apk" / "x.apk").touch()
    with pytest.raises(FileNotFoundError, match="hardened"):
        bundle.validate_build_artifacts(tmp_path / "apps" / "x")
