from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


class ReplayRunError(Exception):
    """Base class for replay-run preflight failures."""


class ReplaySourceNotFoundError(ReplayRunError):
    """Raised when the requested source run directory is missing."""


class ReplayMetadataError(ReplayRunError):
    """Raised when replay-run metadata is missing or inconsistent."""


class ReplayCompatibilityError(ReplayRunError):
    """Raised when explicit runner inputs conflict with source-run metadata."""


class ReplayArtifactError(ReplayRunError):
    """Raised when a replay source does not contain a usable exploit artifact."""


@dataclass
class ReplayRunMetadata:
    source_path: Path
    source_run_id: str | None = None
    app_name: str | None = None
    workflow: str | None = None
    task: str | None = None
    attack_model: str | None = None
    source_outcome: str | None = None
    warnings: list[str] = field(default_factory=list)
    metadata_sources: dict[str, str] = field(default_factory=dict)


@dataclass
class ExploitArtifactSpec:
    attack_model: Literal["malicious_app", "auth_attacker"]
    artifact_kind: str
    source_dir: Path
    warnings: list[str] = field(default_factory=list)


@dataclass
class ReplayRunSpec:
    metadata: ReplayRunMetadata
    artifact: ExploitArtifactSpec

    @property
    def warnings(self) -> list[str]:
        return [*self.metadata.warnings, *self.artifact.warnings]

    def to_record(self) -> dict:
        return {
            "mode": "replay_run",
            "source_path": str(self.metadata.source_path),
            "source_run_id": self.metadata.source_run_id,
            "source_app": self.metadata.app_name,
            "source_task": self.metadata.task,
            "source_workflow": self.metadata.workflow,
            "source_attack_model": self.metadata.attack_model,
            "source_outcome": self.metadata.source_outcome,
            "artifact_kind": self.artifact.artifact_kind,
            "warnings": self.warnings,
            "metadata_sources": self.metadata.metadata_sources,
        }


def resolve_replay_run(
    replay_run: str | Path,
    *,
    project_root: Path,
    explicit_app_name: str | None,
    explicit_task: str | None,
    explicit_workflow: str | None,
    explicit_attack_model: str | None,
) -> ReplayRunSpec:
    source_path = _resolve_replay_source_path(replay_run, project_root)
    metadata = _load_replay_metadata(source_path)
    _apply_explicit_compatibility_checks(
        metadata,
        explicit_app_name=explicit_app_name,
        explicit_task=explicit_task,
        explicit_workflow=explicit_workflow,
        explicit_attack_model=explicit_attack_model,
    )

    if explicit_app_name and not metadata.app_name:
        metadata.app_name = explicit_app_name
        metadata.metadata_sources["app_name"] = "explicit"
    if explicit_task and not metadata.task:
        metadata.task = explicit_task
        metadata.metadata_sources["task"] = "explicit"
    if explicit_workflow and not metadata.workflow:
        metadata.workflow = explicit_workflow
        metadata.metadata_sources["workflow"] = "explicit"
    if explicit_attack_model and not metadata.attack_model:
        metadata.attack_model = explicit_attack_model
        metadata.metadata_sources["attack_model"] = "explicit"

    workflow = metadata.workflow or explicit_workflow
    if workflow and workflow != "redteam":
        raise ReplayCompatibilityError(
            "Replay source unsupported: source workflow is "
            f"{workflow!r}; replay-run currently supports redteam only"
        )
    metadata.workflow = workflow or "redteam"
    metadata.metadata_sources.setdefault("workflow", "default")

    artifact = _resolve_replay_artifact(source_path / "agent_exploit")

    if metadata.attack_model and metadata.attack_model != artifact.attack_model:
        raise ReplayCompatibilityError(
            "Replay source mismatch: metadata attack_model is "
            f"{metadata.attack_model!r}, but the saved artifact layout matches "
            f"{artifact.attack_model!r}"
        )

    metadata.attack_model = artifact.attack_model
    metadata.metadata_sources.setdefault("attack_model", "artifact")

    if not metadata.app_name:
        raise ReplayMetadataError(
            "Source metadata is incomplete: could not determine app_name from the "
            "source run. Pass the app name explicitly, e.g. "
            "python runner.py <app_name> --replay-run <experiment_dir>."
        )

    if not metadata.task:
        raise ReplayMetadataError(
            "Source metadata is incomplete: could not determine redteam task from the "
            "source run. Set it in runner_config.json or pass a config file that does."
        )

    if metadata.source_outcome and metadata.source_outcome != "success":
        metadata.warnings.append(
            "Source run outcome was "
            f"{metadata.source_outcome!r}, but a replayable exploit artifact was found. "
            "Proceeding with replay."
        )

    return ReplayRunSpec(metadata=metadata, artifact=artifact)


def stage_replay_artifact(
    replay_spec: ReplayRunSpec,
    *,
    logs_dir: Path,
    project_root: Path,
) -> tuple[Path, Path]:
    source_dir = replay_spec.artifact.source_dir
    target_dir = logs_dir / "agent_exploit"
    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(source_dir, target_dir)

    if replay_spec.artifact.attack_model == "malicious_app":
        _inject_canonical_build_script(target_dir, project_root)
    elif replay_spec.artifact.attack_model == "auth_attacker":
        exploit_sh = target_dir / "exploit.sh"
        if exploit_sh.exists():
            os.chmod(exploit_sh, os.stat(exploit_sh).st_mode | 0o111)

    replay_source_path = logs_dir / "replay_source.json"
    replay_source_path.write_text(json.dumps(replay_spec.to_record(), indent=2) + "\n")
    return target_dir, replay_source_path


def _resolve_replay_source_path(replay_run: str | Path, project_root: Path) -> Path:
    source_path = Path(replay_run).expanduser()
    candidates = [source_path]
    if not source_path.is_absolute():
        candidates.append(project_root / source_path)

    for candidate in candidates:
        if candidate.exists():
            if not candidate.is_dir():
                raise ReplaySourceNotFoundError(
                    f"Replay source invalid: {candidate} exists but is not a directory"
                )
            return candidate.resolve()

    raise ReplaySourceNotFoundError(
        f"Replay source not found: {replay_run}. "
        "Pass a logs/experiment_<uuid> directory."
    )


def _load_replay_metadata(source_path: Path) -> ReplayRunMetadata:
    metadata = ReplayRunMetadata(source_path=source_path)

    run_summary_path = source_path / "run_summary.json"
    if run_summary_path.exists():
        try:
            run_summary = json.loads(run_summary_path.read_text(encoding="utf-8"))
            context = run_summary.get("context", {}) or {}
            full_snapshot = (
                run_summary.get("config", {}).get("full_snapshot", {}) or {}
            )
            results = run_summary.get("results", {}) or {}

            metadata.source_run_id = run_summary.get("run_id") or metadata.source_run_id
            if context.get("app_name"):
                metadata.app_name = context["app_name"]
                metadata.metadata_sources["app_name"] = str(run_summary_path)
            if context.get("workflow"):
                metadata.workflow = context["workflow"]
                metadata.metadata_sources["workflow"] = str(run_summary_path)
            if full_snapshot.get("task"):
                metadata.task = full_snapshot["task"]
                metadata.metadata_sources["task"] = str(run_summary_path)
            if full_snapshot.get("attack_model"):
                metadata.attack_model = full_snapshot["attack_model"]
                metadata.metadata_sources["attack_model"] = str(run_summary_path)
            if run_summary.get("outcome"):
                metadata.source_outcome = run_summary["outcome"]
            elif results.get("status"):
                metadata.source_outcome = results["status"]
        except Exception as e:
            metadata.warnings.append(
                f"Failed to parse {run_summary_path}: {e}. Falling back to other metadata."
            )

    redteam_scores_path = source_path / "redteam_scores.json"
    if redteam_scores_path.exists():
        try:
            redteam_scores = json.loads(redteam_scores_path.read_text(encoding="utf-8"))
            if redteam_scores.get("workflow") and not metadata.workflow:
                metadata.workflow = redteam_scores["workflow"]
                metadata.metadata_sources["workflow"] = str(redteam_scores_path)
            if redteam_scores.get("task") and not metadata.task:
                metadata.task = redteam_scores["task"]
                metadata.metadata_sources["task"] = str(redteam_scores_path)
            if redteam_scores.get("attack_model") and not metadata.attack_model:
                metadata.attack_model = redteam_scores["attack_model"]
                metadata.metadata_sources["attack_model"] = str(redteam_scores_path)
        except Exception as e:
            metadata.warnings.append(
                f"Failed to parse {redteam_scores_path}: {e}. Falling back to artifact heuristics."
            )

    return metadata


def _apply_explicit_compatibility_checks(
    metadata: ReplayRunMetadata,
    *,
    explicit_app_name: str | None,
    explicit_task: str | None,
    explicit_workflow: str | None,
    explicit_attack_model: str | None,
) -> None:
    _check_field_conflict(
        field_name="app",
        explicit_value=explicit_app_name,
        metadata_value=metadata.app_name,
    )
    _check_field_conflict(
        field_name="task",
        explicit_value=explicit_task,
        metadata_value=metadata.task,
    )
    _check_field_conflict(
        field_name="workflow",
        explicit_value=explicit_workflow,
        metadata_value=metadata.workflow,
    )
    _check_field_conflict(
        field_name="attack_model",
        explicit_value=explicit_attack_model,
        metadata_value=metadata.attack_model,
    )


def _check_field_conflict(
    *, field_name: str, explicit_value: str | None, metadata_value: str | None
) -> None:
    if explicit_value and metadata_value and explicit_value != metadata_value:
        raise ReplayCompatibilityError(
            f"Replay source mismatch: source run {field_name} is {metadata_value!r}, "
            f"but the current request uses {explicit_value!r}."
        )


def _resolve_replay_artifact(agent_exploit_dir: Path) -> ExploitArtifactSpec:
    if not agent_exploit_dir.exists():
        raise ReplayArtifactError(
            f"Replay source invalid: {agent_exploit_dir} not found. This usually means "
            "the source run ended before the agent submitted an exploit."
        )
    if not agent_exploit_dir.is_dir():
        raise ReplayArtifactError(
            f"Replay source invalid: {agent_exploit_dir} exists but is not a directory."
        )

    exploit_sh = agent_exploit_dir / "exploit.sh"
    exploit_apk_dir = agent_exploit_dir / "exploit_apk"
    manifest = exploit_apk_dir / "AndroidManifest.xml"
    java_sources = list((exploit_apk_dir / "src").rglob("*.java"))

    auth_candidate = exploit_sh.exists()
    malicious_candidate = manifest.exists() or exploit_apk_dir.exists()

    if auth_candidate and malicious_candidate:
        if manifest.exists() and java_sources:
            raise ReplayArtifactError(
                "Replay source invalid: both exploit.sh and a malicious-app exploit_apk/ "
                "project were found under agent_exploit/. The replay source must contain "
                "exactly one exploit artifact shape."
            )
        # exploit_apk/ may exist as an empty scratch dir; prefer exploit.sh in that case.
        if not manifest.exists() and not java_sources:
            return ExploitArtifactSpec(
                attack_model="auth_attacker",
                artifact_kind="exploit_shell_script",
                source_dir=agent_exploit_dir,
            )

    if auth_candidate:
        return ExploitArtifactSpec(
            attack_model="auth_attacker",
            artifact_kind="exploit_shell_script",
            source_dir=agent_exploit_dir,
        )

    if exploit_apk_dir.exists() and not manifest.exists():
        raise ReplayArtifactError(
            "Replay source invalid for malicious_app: exploit_apk/ exists, but "
            "exploit_apk/AndroidManifest.xml is missing."
        )

    if manifest.exists() and not java_sources:
        raise ReplayArtifactError(
            "Replay source invalid for malicious_app: expected Java sources under "
            "exploit_apk/src/, but none were found."
        )

    if manifest.exists() and java_sources:
        return ExploitArtifactSpec(
            attack_model="malicious_app",
            artifact_kind="exploit_apk_project",
            source_dir=agent_exploit_dir,
        )

    raise ReplayArtifactError(
        "Replay source invalid: no supported exploit artifact was found under "
        f"{agent_exploit_dir}. Expected either agent_exploit/exploit.sh or a "
        "malicious-app project under agent_exploit/exploit_apk/."
    )


def _inject_canonical_build_script(target_dir: Path, project_root: Path) -> None:
    build_script = project_root / "templates" / "malicious_app" / "build_exploit_apk.sh"
    if not build_script.exists():
        raise ReplayArtifactError(
            f"Canonical malicious-app build script not found: {build_script}"
        )

    apk_dir = target_dir / "exploit_apk"
    apk_dir.mkdir(parents=True, exist_ok=True)
    target_build_script = apk_dir / "build_exploit_apk.sh"
    shutil.copy2(build_script, target_build_script)
    os.chmod(target_build_script, os.stat(target_build_script).st_mode | 0o111)
