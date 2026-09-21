"""Task-bundle abstraction for RedTeamWorkflow.

One workflow, two bundle types:

- ZerodayBundle → apps/<app>/zero_day_vulnerabilities/<task>/
  Baseline is vulnerable; fix.patch turns it patched. Phase 1 is no-op on
  codebase; Phase 2 applies fix.patch.

- ProbeOnlyBundle → apps/<app>/ (no task directory)
  No patch, no verifier. Single clean phase. Used for probe-only runs
  against an APK with optional source codebase. attacker_model is supplied
  at construction (from RunnerConfig) since there is no task metadata.

The workflow never branches on bundle kind for path resolution; phase-prep
and patch/build operations are guarded by `kind` checks where probe-only mode
bypasses them entirely.
"""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Literal, Optional, Protocol, runtime_checkable

from utils.apk_utils import resolve_apk_path
from utils.git_utils import git_restore_clean

BundleKind = Literal["zeroday", "probe_only"]


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


def _read_server_side_from_metadata(metadata_path: Path) -> Optional[dict]:
    """Return the ``server_side`` block from task metadata.json, or None.

    Present iff ``fix.patch`` targets the backend server rather than the
    Android app (see ``evaluation.backend_image_swap``). Validated shallowly
    here; the JSON schema (``zero_day_task_bundle_schema.json``) is the
    authoritative contract.
    """
    try:
        if not metadata_path.exists():
            return None
        ss = json.loads(metadata_path.read_text()).get("server_side")
    except (OSError, json.JSONDecodeError, ValueError):
        # Unreadable / malformed metadata → treat as app-side (no swap). Keeps
        # phase2_apk()/is_server_side() side-effect-free for path-only callers.
        return None
    if ss is None:
        return None
    if (
        not isinstance(ss, dict)
        or not ss.get("service")
        or not isinstance(ss.get("images"), dict)
    ):
        raise ValueError(
            f"server_side in {metadata_path} must define 'service' and an "
            f"'images' object with 'vulnerable'/'secure' refs; got {ss!r}"
        )
    return ss


def _run_build(project_root: Path, args: list[str], timeout: int) -> None:
    from utils.command_executor import CommandExecutor

    CommandExecutor().run_with_progress(
        f"bash ./build_apk.sh {' '.join(args)}",
        timeout=timeout,
        message=f"Building APK: {' '.join(args)}",
        cwd=project_root,
    )


@dataclass(frozen=True)
class ZerodayBundle:
    project_root: Path
    app_name: str
    task: str
    # APK obfuscation toggle context
    runner_obfuscation: str = "off"
    kind: BundleKind = "zeroday"

    def __post_init__(self) -> None:
        # refuse the obfuscation + zeroday combination at construction time. Phase 1 honors --obfuscate,
        # Phase 2 cannot (build_apk.sh rejects --obfuscate + --hardened-patch),
        # so the agent attacks an obfuscated APK and the verifier replays
        # against an un-obfuscated hardened APK — different runtime envs for
        # the same task. The CI matrix already carves zeroday out of the
        # obfuscated combos; this enforces it for non-CI runners too.
        if self.runner_obfuscation == "on":
            raise ValueError(
                "apk_obfuscation: 'on' is not supported with zeroday tasks: "
                "Phase 1 would be R8-minified but Phase 2 (the hardened APK) "
                "cannot be — build_apk.sh rejects --obfuscate + "
                "--hardened-patch. Run with apk_obfuscation: 'off' or omit the "
                "zeroday task from the run."
            )

    @property
    def _task_root(self) -> Path:
        return self.project_root / "apps" / self.app_name / "zero_day_vulnerabilities"

    @property
    def task_dir(self) -> Path:
        return self._task_root / self.task

    @property
    def exploit_dir(self) -> Path:
        return self.task_dir / "exploit_files"

    @property
    def patch(self) -> Path:
        return self.task_dir / "fix.patch"

    def attacker_model(self) -> str:
        return _read_attacker_model_from_metadata(self.task_dir / "metadata.json")

    def server_side(self) -> Optional[dict]:
        """Return the ``server_side`` metadata block, or None for app-side tasks."""
        return _read_server_side_from_metadata(self.task_dir / "metadata.json")

    def is_server_side(self) -> bool:
        return self.server_side() is not None

    def backend_service(self) -> str:
        """Compose service whose image is swapped per phase."""
        ss = self.server_side()
        if ss is None:
            raise ValueError(f"{self.task} is not a server-side task")
        return ss["service"]

    def backend_image_for_phase(self, phase_slug: str) -> str:
        """Prebuilt backend image ref for a runner phase slug.

        ``phase_slug`` is ``vulnerable`` (Phase 1) or ``secure`` (Phase 2),
        matching ``_phase_slug_for_output_dir`` in the workflow.
        """
        ss = self.server_side()
        if ss is None:
            raise ValueError(f"{self.task} is not a server-side task")
        from evaluation.backend_image_swap import image_key_for_phase

        key = image_key_for_phase(phase_slug)
        if key is None:
            raise ValueError(f"unknown phase slug {phase_slug!r} for image swap")
        image = ss["images"].get(key)
        if not image:
            raise ValueError(f"server_side.images.{key} missing for task {self.task}")
        return image

    @property
    def _hardened_apk(self) -> Path:
        return (
            self._task_root
            / "artifacts"
            / self.task
            / "hardened_apk"
            / f"{self.app_name}.apk"
        )

    def phase1_apk(self) -> Path:
        """Vulnerable APK: the default build target (baseline is vulnerable).

        Path layout honors apk_obfuscation via resolve_apk_path.
        """
        app_dir = self.project_root / "apps" / self.app_name
        return app_dir / resolve_apk_path(
            app_name=self.app_name,
            runner_obfuscation=self.runner_obfuscation,
            vuln_id=None,
        )

    def phase2_apk(self) -> Path:
        """Patched APK: prebuilt and cached under artifacts/.

        Hardened APK path is fixed by the report layout; build_apk.sh's
        validator rejects --obfuscate + --hardened-patch as unsupported, so
        the toggle does not split phase 2.

        Server-side tasks patch the backend, not the app: the APK is identical
        across phases, so Phase 2 replays the same baseline APK as Phase 1.
        """
        if self.is_server_side():
            return self.phase1_apk()
        return self._hardened_apk

    def restore_codebase(self, codebase_dir: Path) -> None:
        git_restore_clean(codebase_dir)

    def prepare_phase1_codebase(self, codebase_dir: Path) -> None:
        """Baseline is already vulnerable — ensure clean checkout."""
        self.restore_codebase(codebase_dir)

    def prepare_phase2_codebase(self, codebase_dir: Path) -> None:
        """Vulnerable → patched: apply fix.patch.

        Server-side tasks patch the backend image (swapped per phase by the
        runner), not the app codebase — so the app tree stays clean and only
        needs a restore. See ``evaluation.backend_image_swap``.
        """
        self.restore_codebase(codebase_dir)
        if self.is_server_side():
            return
        _git_apply(codebase_dir, self.patch)

    def build_apks(self, app_name: str, project_root: Path, *, timeout: int) -> None:
        # Phase 1 (vulnerable baseline) honors --obfuscate. Phase 2 (hardened)
        # cannot — build_apk.sh's validator rejects --obfuscate + --hardened-patch.
        obf_flag = ["--obfuscate"] if self.runner_obfuscation == "on" else []
        _run_build(project_root, [app_name, *obf_flag], timeout)
        # Server-side tasks reuse the baseline APK in both phases (the patch is
        # in the backend image), so there is no hardened APK to build.
        if self.is_server_side():
            return
        _run_build(
            project_root,
            [app_name, "--hardened-patch", str(self.patch)],
            timeout,
        )

    def validate_build_artifacts(self, app_dir: Path) -> None:
        if not self.phase1_apk().exists():
            raise FileNotFoundError(f"Original APK not found: {self.phase1_apk()}")
        # Server-side tasks have no hardened APK — Phase 2 reuses phase1_apk.
        if self.is_server_side():
            return
        if not self._hardened_apk.exists():
            raise FileNotFoundError(
                f"Prebuilt hardened APK not found for task {self.task}: "
                f"{self._hardened_apk}. Run once with build_type='source'."
            )


@dataclass(frozen=True)
class ProbeOnlyBundle:
    """Bundle stub for probe-only runs against an app with no task bundle.

    Used when no zeroday task exists: open-source apps without a bundle, and
    APK-only / closed-source apps. The agent runs against the clean app build,
    probes score the result, and there is no patch / verifier / phase 2.

    `attacker_model` is supplied at construction (from RunnerConfig) since
    there is no task metadata.json to read from.
    """

    app_dir: Path
    _attacker_model: str
    # APK obfuscation toggle context.
    runner_obfuscation: str = "off"
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


def resolve_bundle(config, project_root: Path, app_name: str) -> TaskBundle:
    """Return the TaskBundle for the current config.

    - probe_only=True → ProbeOnlyBundle (config validator guarantees no task
      and an explicit attacker_model)
    - task set → ZerodayBundle
    Synthetic-vulnerability selectors are retired and rejected by RunnerConfig.

    Pure path-resolution. Task existence is checked by workflow validation.
    """
    task = getattr(config, "task", None)
    vuln_id = getattr(config, "synthetic_vuln_id", None)
    probe_only = getattr(config, "probe_only", False)
    runner_obfuscation = getattr(config, "apk_obfuscation", "off")

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
        )

    if vuln_id is not None:
        raise ValueError(
            "synthetic_vuln_id is retired; synthetic vulnerabilities are "
            "archived under archive/synthetic-vulnerabilities/."
        )
    if not task:
        raise ValueError(
            "TaskBundle requires config.task for zero-day runs, or "
            "probe_only=True for bundle-less probe runs; got task=None."
        )
    return ZerodayBundle(
        project_root=project_root,
        app_name=app_name,
        task=task,
        runner_obfuscation=runner_obfuscation,
    )


def build_task_runtime_env(
    *,
    bundle: TaskBundle,
    app_dir: Path,
    attacker_model: str,
    output_dir: Optional[Path] = None,
    phase: Optional[str] = None,
) -> Dict[str, str]:
    """Return the canonical ``MCB_*`` env-var dict for task-bundle hooks.

    Mirrors the contract that ``scripts/task_runtime_common.sh``
    (``task_runtime_set_context``) exports so that hooks (``prepare_app``,
    ``prepare_victim``, ``agent_login``, etc.) behave identically whether
    invoked through ``scripts/validate_task_bundle.sh`` or through
    ``runner.py``.

    Callers merge the result into ``os.environ.copy()`` before passing it as
    the ``env=`` kwarg of the subprocess that runs the hook.

    The returned dict is bundle-aware: per-task fields
    (``MCB_TASK_DIR``, ``MCB_TASK_METADATA_JSON``, ``MCB_TASK_ID``,
    ``MCB_FIX_PATCH``) are populated only when the bundle has a task; for
    ``ProbeOnlyBundle`` (bundle-less probe-only mode) those keys are
    omitted. Reads ``apps/<app>/metadata.json`` opportunistically to fill
    ``MCB_PACKAGE_NAME`` and ``MCB_BASELINE_COMMIT``.
    """
    env: Dict[str, str] = {}
    env["MCB_APP_DIR"] = str(app_dir)
    env["MCB_ATTACKER_MODEL"] = attacker_model

    app_metadata_path = app_dir / "metadata.json"
    app_meta: dict = {}
    if app_metadata_path.exists():
        env["MCB_APP_METADATA_JSON"] = str(app_metadata_path)
        try:
            app_meta = json.loads(app_metadata_path.read_text())
        except (json.JSONDecodeError, OSError):
            app_meta = {}

    # Per-task fields are bundle-aware. ProbeOnlyBundle exposes task_dir
    # for layout symmetry (returns app_dir) and raises on patch access, so
    # we gate on `kind` to set per-task MCB_* keys only for real tasks.
    bundle_kind = getattr(bundle, "kind", None)
    task_meta: dict = {}
    if bundle_kind == "zeroday":
        task_dir = getattr(bundle, "task_dir", None)
        if task_dir is not None:
            env["MCB_TASK_DIR"] = str(task_dir)
            task_metadata_path = Path(task_dir) / "metadata.json"
            if task_metadata_path.exists():
                env["MCB_TASK_METADATA_JSON"] = str(task_metadata_path)
                try:
                    task_meta = json.loads(task_metadata_path.read_text())
                except (json.JSONDecodeError, OSError):
                    task_meta = {}

        # MCB_FIX_PATCH semantics match scripts/task_runtime_common.sh:
        # it carries the hardening / fix patch the validator passes in
        # (`task/fix.patch` for zero-day bundles).
        try:
            patch_path = getattr(bundle, "patch", None)
        except (AttributeError, NotImplementedError):
            patch_path = None
        if patch_path is not None:
            patch_path = Path(patch_path)
            if patch_path.exists():
                env["MCB_FIX_PATCH"] = str(patch_path)

    # Apply the validator's precedence rules from
    # scripts/zero_day_task_common.sh so MCB_TASK_ID / MCB_PACKAGE_NAME /
    # MCB_BASELINE_COMMIT match what hooks would see under
    # scripts/validate_task_bundle.sh.
    #
    # task_id: task metadata `.task_id` > `.task_slug` > bundle.task.
    # package_name: task metadata `.runtime.package_name` >
    #               `.app_metadata_overrides.package_name` >
    #               app metadata `.package_name`.
    # baseline commit: task metadata `.baseline.commit` >
    #                  app metadata `.commit_version`.
    task_id = task_meta.get("task_id") or task_meta.get("task_slug")
    if not (isinstance(task_id, str) and task_id):
        task_id = getattr(bundle, "task", None)
    if isinstance(task_id, str) and task_id:
        env["MCB_TASK_ID"] = task_id

    runtime_section = (
        task_meta.get("runtime") if isinstance(task_meta.get("runtime"), dict) else {}
    )
    overrides_section = (
        task_meta.get("app_metadata_overrides")
        if isinstance(task_meta.get("app_metadata_overrides"), dict)
        else {}
    )
    package_name = (
        runtime_section.get("package_name")
        or overrides_section.get("package_name")
        or app_meta.get("package_name")
    )
    if isinstance(package_name, str) and package_name:
        env["MCB_PACKAGE_NAME"] = package_name

    baseline_section = (
        task_meta.get("baseline") if isinstance(task_meta.get("baseline"), dict) else {}
    )
    baseline_commit = baseline_section.get("commit") or app_meta.get("commit_version")
    if isinstance(baseline_commit, str) and baseline_commit:
        env["MCB_BASELINE_COMMIT"] = baseline_commit

    if output_dir is not None:
        env["MCB_OUTPUT_DIR"] = str(output_dir)

    if phase:
        env["MCB_PHASE"] = str(phase)

    return env
