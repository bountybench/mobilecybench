"""Task-bundle abstraction for RedTeamWorkflow.

One workflow, three bundle types:

- SyntheticBundle → apps/<app>/synthetic_vulnerabilities/<vuln_id>/
  Baseline is clean; vulnerability.patch turns it vulnerable. Phase 1 applies
  the patch; Phase 2 reverts.

- ZerodayBundle → zerodays/reports/<app>/<task>/task/
  Baseline is vulnerable; fix.patch turns it patched. Phase 1 is no-op on
  codebase; Phase 2 applies fix.patch.

- ProbeOnlyBundle → apps/<app>/ (no task directory)
  No patch, no verifier. Single clean phase. Used for probe-only runs
  against an APK with optional source codebase. attacker_model is supplied
  at construction (from RunnerConfig) since there is no task metadata.

The workflow never branches on bundle kind for path resolution; phase-prep
and patch/build operations are guarded by `kind` checks where probe-only
mode bypasses them entirely.
"""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, cast, get_args, runtime_checkable

from models.config import AttackerModel
from utils.git_utils import git_restore_clean

BundleKind = Literal["synthetic", "zeroday", "probe_only"]
_VALID_ATTACKER_MODELS: frozenset[str] = frozenset(get_args(AttackerModel))


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
        ProbeOnly: not applicable — raises NotImplementedError.
        """
        ...

    def attacker_model(self) -> AttackerModel:
        """Authoritative attacker_model for this bundle.

        Bundle-backed: read from task_dir/metadata.json.
        Probe-only:    supplied at construction from RunnerConfig.
        """
        ...

    def phase1_apk(self) -> Path: ...
    def phase2_apk(self) -> Path: ...
    def prepare_phase1_codebase(self, codebase_dir: Path) -> None: ...
    def prepare_phase2_codebase(self, codebase_dir: Path) -> None: ...
    def restore_codebase(self, codebase_dir: Path) -> None: ...
    def build_apks(
        self, app_name: str, project_root: Path, *, timeout: int
    ) -> None: ...
    def validate_build_artifacts(self, app_dir: Path) -> None: ...


def _read_attacker_model_from_metadata(metadata_path: Path) -> AttackerModel:
    if not metadata_path.exists():
        raise ValueError(f"metadata.json not found at {metadata_path}")
    am = json.loads(metadata_path.read_text()).get("attacker_model")
    if am not in _VALID_ATTACKER_MODELS:
        raise ValueError(
            f"attacker_model={'missing' if am is None else repr(am)} "
            f"in {metadata_path} (must be one of {_VALID_ATTACKER_MODELS})"
        )
    # ``am`` is now proven to be one of ``AttackerModel``'s Literal values.
    return cast(AttackerModel, am)


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

    def attacker_model(self) -> AttackerModel:
        return _read_attacker_model_from_metadata(self.task_dir / "metadata.json")

    def phase1_apk(self) -> Path:
        """Vulnerable APK: built via --vuln synthetic_vulnerabilities/<vuln>."""
        return self.app_dir / "apk" / self.vuln_id / f"{self.app_dir.name}.apk"

    def phase2_apk(self) -> Path:
        """Clean APK: the default build target."""
        return self.app_dir / "apk" / f"{self.app_dir.name}.apk"

    def restore_codebase(self, codebase_dir: Path) -> None:
        """Reset codebase to a clean state (HEAD + no untracked files)."""
        git_restore_clean(codebase_dir)

    def prepare_phase1_codebase(self, codebase_dir: Path) -> None:
        """Clean → vulnerable: apply the synthetic patch."""
        self.restore_codebase(codebase_dir)
        _git_apply(codebase_dir, self.patch)

    def prepare_phase2_codebase(self, codebase_dir: Path) -> None:
        """Vulnerable → clean: revert to HEAD."""
        self.restore_codebase(codebase_dir)

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

    def attacker_model(self) -> AttackerModel:
        return _read_attacker_model_from_metadata(self.task_dir / "metadata.json")

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

    def restore_codebase(self, codebase_dir: Path) -> None:
        git_restore_clean(codebase_dir)

    def prepare_phase1_codebase(self, codebase_dir: Path) -> None:
        """Baseline is already vulnerable — ensure clean checkout."""
        self.restore_codebase(codebase_dir)

    def prepare_phase2_codebase(self, codebase_dir: Path) -> None:
        """Vulnerable → patched: apply fix.patch."""
        self.restore_codebase(codebase_dir)
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


@dataclass(frozen=True)
class ProbeOnlyBundle:
    """Bundle stub for probe-only runs against an app with no task bundle.

    Used when no synthetic vuln or zeroday task exists: open-source apps
    without a bundle, and APK-only / closed-source apps. The agent runs
    against the clean app build, probes score the result, and there is
    no patch / verifier / phase 2.

    `attacker_model` is supplied at construction (from RunnerConfig) since
    there is no task metadata.json to read from.
    """

    app_dir: Path
    _attacker_model: AttackerModel
    kind: BundleKind = "probe_only"

    @property
    def task_dir(self) -> Path:
        return self.app_dir

    @property
    def exploit_dir(self) -> Path:
        return self.app_dir

    @property
    def patch(self) -> Path:
        raise NotImplementedError("probe_only has no patch")

    def attacker_model(self) -> AttackerModel:
        return self._attacker_model

    def phase1_apk(self) -> Path:
        return self.app_dir / "apk" / f"{self.app_dir.name}.apk"

    def phase2_apk(self) -> Path:
        return self.phase1_apk()

    def restore_codebase(self, codebase_dir: Path) -> None:
        # probe_only restores via _prepare_runtime_codebase, not the bundle
        pass

    def prepare_phase1_codebase(self, codebase_dir: Path) -> None:
        # Probe-only's runtime codebase prep runs git_restore_clean directly
        # in RedTeamWorkflow._prepare_runtime_codebase; this Protocol method
        # is a no-op so any incidental call is safe.
        pass

    def prepare_phase2_codebase(self, codebase_dir: Path) -> None:
        raise NotImplementedError("probe_only never enters phase 2")

    def build_apks(self, app_name: str, project_root: Path, *, timeout: int) -> None:
        # Build only the clean baseline APK (apps/<app>/apk/<app>.apk).
        # Probe-only never produces a vuln-variant or hardened APK because
        # there is no patch.
        _run_build(project_root, [app_name], timeout)

    def validate_build_artifacts(self, app_dir: Path) -> None:
        if not self.phase1_apk().exists():
            raise FileNotFoundError(f"Probe-only APK not found: {self.phase1_apk()}")


def assert_zerodays_initialized(project_root: Path) -> None:
    """Surface a clear, actionable error when zerodays/ is empty.

    The submodule is registered in .gitmodules but `bash setup.sh` only
    initializes it with --init-submodules. A bare clone leaves the
    directory empty, and downstream code that opens task/metadata.json
    raises a path-not-found error that does not point at the submodule.

    Callers run this as an environment precondition before exercising a
    ZerodayBundle's filesystem paths (validate_arguments hooks, runner
    startup metadata reads).
    """
    zerodays_dir = project_root / "zerodays"
    if zerodays_dir.exists() and any(zerodays_dir.iterdir()):
        return
    raise FileNotFoundError(
        "zerodays/ submodule is not initialized — required for redteam "
        "zero-day tasks. Run:\n"
        "    git submodule update --init zerodays\n"
        "If you do not have access to the submodule remote, contact a "
        "repo maintainer."
    )
