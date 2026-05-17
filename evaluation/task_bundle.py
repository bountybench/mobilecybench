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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from utils.apk_utils import resolve_apk_path
from utils.git_utils import git_restore_clean

BundleKind = Literal["synthetic", "zeroday", "probe_only"]


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

    def attacker_model(self) -> str:
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


_VALID_ATTACKER_MODELS = {"malicious_app", "remote_attacker"}


def _read_attacker_model_from_metadata(metadata_path: Path) -> str:
    if not metadata_path.exists():
        raise ValueError(f"metadata.json not found at {metadata_path}")
    am = json.loads(metadata_path.read_text()).get("attacker_model")
    if am not in _VALID_ATTACKER_MODELS:
        raise ValueError(
            f"attacker_model={'missing' if am is None else repr(am)} "
            f"in {metadata_path} (must be one of {_VALID_ATTACKER_MODELS})"
        )
    return am


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
    # APK obfuscation toggle resolution context. Passed by resolve_bundle()
    # from RunnerConfig + the app's metadata.json.
    runner_obfuscation: str = "off"
    app_metadata: dict = field(default_factory=dict)
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

    def attacker_model(self) -> str:
        return _read_attacker_model_from_metadata(self.task_dir / "metadata.json")

    def phase1_apk(self) -> Path:
        """Vulnerable APK: built via --vuln synthetic_vulnerabilities/<vuln>.

        Path layout honors apk_obfuscation: see resolve_apk_path.
        """
        return self.app_dir / resolve_apk_path(
            app_name=self.app_dir.name,
            runner_obfuscation=self.runner_obfuscation,
            app_metadata=self.app_metadata,
            vuln_id=self.vuln_id,
        )

    def phase2_apk(self) -> Path:
        """Clean APK: the default build target.

        Path layout honors apk_obfuscation: see resolve_apk_path.
        """
        return self.app_dir / resolve_apk_path(
            app_name=self.app_dir.name,
            runner_obfuscation=self.runner_obfuscation,
            app_metadata=self.app_metadata,
            vuln_id=None,
        )

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
        # When obfuscation is requested, pass --obfuscate to build_apk.sh so
        # build_apk.sh's M2 mechanism (gradle init script) takes effect and
        # the output lands at apps/<app>/apk/obfuscated/[vuln_id/]<app>.apk —
        # the same path resolve_apk_path() points phase1_apk()/phase2_apk() at.
        obf_flag = ["--obfuscate"] if self.runner_obfuscation == "on" else []
        _run_build(project_root, [app_name, *obf_flag], timeout)
        _run_build(
            project_root,
            [
                app_name,
                "--vuln",
                f"synthetic_vulnerabilities/{self.vuln_id}",
                *obf_flag,
            ],
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
    # APK obfuscation toggle context
    runner_obfuscation: str = "off"
    app_metadata: dict = field(default_factory=dict)
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

    def attacker_model(self) -> str:
        return _read_attacker_model_from_metadata(self.task_dir / "metadata.json")

    @property
    def _hardened_apk(self) -> Path:
        return self._report_dir / "artifacts" / "hardened_apk" / f"{self.app_name}.apk"

    def phase1_apk(self) -> Path:
        """Vulnerable APK: the default build target (baseline is vulnerable).

        Path layout honors apk_obfuscation via resolve_apk_path.
        """
        app_dir = self.project_root / "apps" / self.app_name
        return app_dir / resolve_apk_path(
            app_name=self.app_name,
            runner_obfuscation=self.runner_obfuscation,
            app_metadata=self.app_metadata,
            vuln_id=None,
        )

    def phase2_apk(self) -> Path:
        """Patched APK: prebuilt and cached under artifacts/.

        Hardened APK path is fixed by the report layout; build_apk.sh's
        validator rejects --obfuscate + --hardened-patch as unsupported, so
        the toggle does not split phase 2.
        """
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
        # Phase 1 (vulnerable baseline) honors --obfuscate. Phase 2 (hardened)
        # cannot — build_apk.sh's validator rejects --obfuscate + --hardened-patch.
        obf_flag = ["--obfuscate"] if self.runner_obfuscation == "on" else []
        _run_build(project_root, [app_name, *obf_flag], timeout)
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
    _attacker_model: str
    # APK obfuscation toggle context.
    runner_obfuscation: str = "off"
    app_metadata: dict = field(default_factory=dict)
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

    def attacker_model(self) -> str:
        return self._attacker_model

    def phase1_apk(self) -> Path:
        """Baseline APK; path layout honors apk_obfuscation."""
        return self.app_dir / resolve_apk_path(
            app_name=self.app_dir.name,
            runner_obfuscation=self.runner_obfuscation,
            app_metadata=self.app_metadata,
            vuln_id=None,
        )

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
        # Build only the clean baseline APK. Probe-only never produces a
        # vuln-variant or hardened APK because there is no patch.
        obf_flag = ["--obfuscate"] if self.runner_obfuscation == "on" else []
        _run_build(project_root, [app_name, *obf_flag], timeout)

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


def resolve_bundle(config, project_root: Path, app_name: str) -> TaskBundle:
    """Return the TaskBundle for the current config.

    - probe_only=True → ProbeOnlyBundle (config validator guarantees no
      task / no synthetic_vuln_id and an explicit attacker_model)
    - task set → ZerodayBundle
    - synthetic_vuln_id set → SyntheticBundle

    Bundle-backed runs require strict XOR (task vs synthetic_vuln_id).

    Pure path-resolution — does not check filesystem state. Callers that
    need an environment precondition should invoke
    ``assert_zerodays_initialized`` separately.
    """
    task = getattr(config, "task", None)
    vuln_id = getattr(config, "synthetic_vuln_id", None)
    probe_only = getattr(config, "probe_only", False)
    runner_obfuscation = getattr(config, "apk_obfuscation", "off")
    app_metadata = _load_app_metadata(project_root, app_name)

    if probe_only:
        attacker_model = getattr(config, "attacker_model", None)
        if attacker_model not in _VALID_ATTACKER_MODELS:
            raise ValueError(
                "probe_only requires config.attacker_model in "
                f"{_VALID_ATTACKER_MODELS}; got {attacker_model!r}"
            )
        return ProbeOnlyBundle(
            app_dir=project_root / "apps" / app_name,
            _attacker_model=attacker_model,
            runner_obfuscation=runner_obfuscation,
            app_metadata=app_metadata,
        )

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
            runner_obfuscation=runner_obfuscation,
            app_metadata=app_metadata,
        )
    assert vuln_id is not None
    return SyntheticBundle(
        app_dir=project_root / "apps" / app_name,
        vuln_id=vuln_id,
        runner_obfuscation=runner_obfuscation,
        app_metadata=app_metadata,
    )


def _load_app_metadata(project_root: Path, app_name: str) -> dict:
    """Load apps/<app>/metadata.json. Returns {} when missing/unreadable so
    bundle construction stays robust in tests that don't touch real apps."""
    metadata_path = project_root / "apps" / app_name / "metadata.json"
    if not metadata_path.exists():
        return {}
    try:
        return json.loads(metadata_path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
