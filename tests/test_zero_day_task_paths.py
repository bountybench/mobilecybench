"""Tests for zero-day task path resolution helpers."""

import os
import subprocess
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]


def _resolve_artifact_root(source_task_dir: Path, task_id: str) -> str:
    env = os.environ.copy()
    env["ROOT_DIR"] = str(ROOT_DIR)
    cmd = (
        f'source "{ROOT_DIR}/scripts/zero_day_task_common.sh" && '
        f'zero_day_task_resolve_artifact_root "{source_task_dir}" "{task_id}"'
    )
    result = subprocess.run(
        ["bash", "-lc", cmd],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _validate_task_id(task_id: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["ROOT_DIR"] = str(ROOT_DIR)
    cmd = (
        f'source "{ROOT_DIR}/scripts/zero_day_task_common.sh" && '
        f'zero_day_task_validate_task_id "{task_id}"'
    )
    return subprocess.run(
        ["bash", "-lc", cmd],
        env=env,
        capture_output=True,
        text=True,
    )


def _validate_source_dir(task_dir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["ROOT_DIR"] = str(ROOT_DIR)
    cmd = (
        f'source "{ROOT_DIR}/scripts/zero_day_task_common.sh" && '
        f'zero_day_task_validate_source_dir "{task_dir}"'
    )
    return subprocess.run(
        ["bash", "-lc", cmd],
        env=env,
        capture_output=True,
        text=True,
    )


def test_report_checkout_artifact_root():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        source_task_dir = tmp / "reports" / "app" / "report-1" / "task"
        source_task_dir.mkdir(parents=True)

        assert _resolve_artifact_root(source_task_dir, "task-1") == str(
            tmp / "reports" / "app" / "report-1" / "artifacts"
        )


def test_public_tree_artifact_root():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        source_task_dir = tmp / "apps" / "app" / "zero_day_vulnerabilities" / "task-1"
        source_task_dir.mkdir(parents=True)

        assert _resolve_artifact_root(source_task_dir, "task-1") == str(
            tmp / "apps" / "app" / "zero_day_vulnerabilities" / "artifacts" / "task-1"
        )


def test_task_id_validation_rejects_path_traversal():
    result = _validate_task_id("../../outside")
    assert result.returncode != 0


def test_source_dir_rejects_symlinks():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        task_dir = tmp / "task"
        (task_dir / "exploit_files").mkdir(parents=True)
        (task_dir / "verify_files").mkdir()
        (task_dir / "metadata.json").write_text(
            '{"schema_version":1,"task_id":"task-1","title":"t","baseline":{"commit":"abc"}}'
        )
        (task_dir / "fix.patch").write_text("diff --git a b\n")
        (task_dir / "exploit_files" / "exploit.sh").write_text("#!/bin/sh\nexit 0\n")
        (task_dir / "verify_files" / "verify_exploit.sh").write_text(
            "#!/bin/sh\nexit 0\n"
        )
        (task_dir / "exploit_files" / "symlink").symlink_to(task_dir / "fix.patch")

        result = _validate_source_dir(task_dir)
        assert result.returncode != 0
