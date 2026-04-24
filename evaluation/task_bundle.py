"""Task-bundle abstraction for RedTeamWorkflow.

One workflow, two bundle types:

- SyntheticBundle → apps/<app>/synthetic_vulnerabilities/<vuln_id>/
  Baseline is clean; vulnerability.patch turns it vulnerable. Phase 1 applies
  the patch; Phase 2 reverts.

- ZerodayBundle → zerodays/reports/<app>/<task>/task/
  Baseline is vulnerable; fix.patch turns it patched. Phase 1 is no-op on
  codebase; Phase 2 applies fix.patch.

The workflow never branches on bundle kind — path resolution and codebase
phase-prep live behind the TaskBundle Protocol.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

BundleKind = Literal["synthetic", "zeroday"]


@runtime_checkable
class TaskBundle(Protocol):
    """Task file layout + phase-prep contract for RedTeamWorkflow."""

    @property
    def kind(self) -> BundleKind: ...
    @property
    def task_dir(self) -> Path: ...
    @property
    def exploit_dir(self) -> Path: ...
    @property
    def patch(self) -> Path:
        """Bundle-specific patch file.

        Synthetic: vulnerability.patch (turns clean → vulnerable).
        Zeroday:   fix.patch (turns vulnerable → patched).
        """
        ...

    def phase1_apk(self) -> Path: ...
    def phase2_apk(self) -> Path: ...
    def prepare_phase1_codebase(self, codebase_dir: Path) -> None: ...
    def prepare_phase2_codebase(self, codebase_dir: Path) -> None: ...
    def build_apks(
        self, app_name: str, project_root: Path, *, timeout: int
    ) -> None: ...
    def validate_build_artifacts(self, app_dir: Path) -> None: ...


def _git_restore(codebase_dir: Path) -> None:
    # TODO(#980): switch to utils.git_utils.git_restore_clean so untracked
    # files from patches are also removed between phase transitions.
    subprocess.run(["git", "checkout", "--", "."], cwd=codebase_dir, check=True)


def _git_apply(codebase_dir: Path, patch: Path) -> None:
    subprocess.run(["git", "apply", str(patch)], cwd=codebase_dir, check=True)


def _run_build(project_root: Path, args: list[str], timeout: int) -> None:
    from utils.command_executor import CommandExecutor

    CommandExecutor().run_with_progress(
        f"bash ./build_apk.sh {' '.join(args)}",
        timeout=timeout,
        message=f"Building APK: {' '.join(args)}",
        cwd=project_root,
    )


@dataclass(frozen=True)
class SyntheticBundle:
    app_dir: Path
    vuln_id: str
    kind: BundleKind = "synthetic"

    @property
    def task_dir(self) -> Path:
        return self.app_dir / "synthetic_vulnerabilities" / self.vuln_id

    @property
    def exploit_dir(self) -> Path:
        return self.task_dir / "exploit_files"

    @property
    def patch(self) -> Path:
        return self.task_dir / "vulnerability.patch"

    def phase1_apk(self) -> Path:
        """Vulnerable APK: built via --vuln synthetic_vulnerabilities/<vuln>."""
        return self.app_dir / "apk" / self.vuln_id / f"{self.app_dir.name}.apk"

    def phase2_apk(self) -> Path:
        """Clean APK: the default build target."""
        return self.app_dir / "apk" / f"{self.app_dir.name}.apk"

    def prepare_phase1_codebase(self, codebase_dir: Path) -> None:
        """Clean → vulnerable: apply the synthetic patch."""
        _git_restore(codebase_dir)
        _git_apply(codebase_dir, self.patch)

    def prepare_phase2_codebase(self, codebase_dir: Path) -> None:
        """Vulnerable → clean: revert to HEAD."""
        _git_restore(codebase_dir)

    def build_apks(self, app_name: str, project_root: Path, *, timeout: int) -> None:
        _run_build(project_root, [app_name], timeout)
        _run_build(
            project_root,
            [app_name, "--vuln", f"synthetic_vulnerabilities/{self.vuln_id}"],
            timeout,
        )

    def validate_build_artifacts(self, app_dir: Path) -> None:
        for apk in (self.phase1_apk(), self.phase2_apk()):
            if not apk.exists():
                raise FileNotFoundError(f"APK not found: {apk}")


@dataclass(frozen=True)
class ZerodayBundle:
    project_root: Path
    app_name: str
    task: str
    kind: BundleKind = "zeroday"

    @property
    def _report_dir(self) -> Path:
        return self.project_root / "zerodays" / "reports" / self.app_name / self.task

    @property
    def task_dir(self) -> Path:
        return self._report_dir / "task"

    @property
    def exploit_dir(self) -> Path:
        return self.task_dir / "exploit_files"

    @property
    def patch(self) -> Path:
        return self.task_dir / "fix.patch"

    @property
    def _hardened_apk(self) -> Path:
        return self._report_dir / "artifacts" / "hardened_apk" / f"{self.app_name}.apk"

    def phase1_apk(self) -> Path:
        """Vulnerable APK: the default build target (baseline is vulnerable)."""
        return (
            self.project_root / "apps" / self.app_name / "apk" / f"{self.app_name}.apk"
        )

    def phase2_apk(self) -> Path:
        """Patched APK: prebuilt and cached under artifacts/."""
        return self._hardened_apk

    def prepare_phase1_codebase(self, codebase_dir: Path) -> None:
        """Baseline is already vulnerable — ensure clean checkout."""
        _git_restore(codebase_dir)

    def prepare_phase2_codebase(self, codebase_dir: Path) -> None:
        """Vulnerable → patched: apply fix.patch."""
        _git_restore(codebase_dir)
        _git_apply(codebase_dir, self.patch)

    def build_apks(self, app_name: str, project_root: Path, *, timeout: int) -> None:
        _run_build(project_root, [app_name], timeout)
        _run_build(
            project_root,
            [app_name, "--hardened-patch", str(self.patch)],
            timeout,
        )

    def validate_build_artifacts(self, app_dir: Path) -> None:
        if not self.phase1_apk().exists():
            raise FileNotFoundError(f"Original APK not found: {self.phase1_apk()}")
        if not self._hardened_apk.exists():
            raise FileNotFoundError(
                f"Prebuilt hardened APK not found for task {self.task}: "
                f"{self._hardened_apk}. Run once with build_type='source'."
            )


def resolve_bundle(config, project_root: Path, app_name: str) -> TaskBundle:
    """Return the TaskBundle for the current config.

    Strict XOR: exactly one of config.task (zeroday) or
    config.synthetic_vuln_id (synthetic) must be set.
    """
    task = getattr(config, "task", None)
    vuln_id = getattr(config, "synthetic_vuln_id", None)

    if bool(task) == bool(vuln_id):
        raise ValueError(
            "TaskBundle requires exactly one of config.task (zeroday) or "
            f"config.synthetic_vuln_id (synthetic); got task={task!r}, "
            f"synthetic_vuln_id={vuln_id!r}."
        )
    if task:
        return ZerodayBundle(
            project_root=project_root,
            app_name=app_name,
            task=task,
        )
    assert vuln_id is not None
    return SyntheticBundle(
        app_dir=project_root / "apps" / app_name,
        vuln_id=vuln_id,
    )
