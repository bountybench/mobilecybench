import datetime
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

import jsonschema

from models.config import (
    ExploitWorkflowInput,
    RedteamSyntheticWorkflowInput,
    RedteamZerodayWorkflowInput,
    RunnerConfig,
)
from models.resolved_config import ResolvedRunnerConfig
from utils.artifact_paths import relative_artifact_path
from utils.json_io import load_validator
from utils.json_io import write_json_atomic as _write_json_atomic
from utils.logger import logger, logger_manager
from utils.time_tracker import time_tracker
from utils.token_costs import derive_cost_from_totals

_RESULT_VALIDATOR = load_validator("result.schema.json")
_RUN_SUMMARY_VALIDATOR = load_validator("run_summary.schema.json")

# None / missing → safe default. Keeps schema validation happy for typed fields
# when an agent emits ``null`` (custom path's max_iterations-without-FINAL hits this).
_RESULT_NULL_DEFAULTS: dict[str, Any] = {
    "model": "",
    "final_message": "",
    "error_traceback": "",
    "tool_call_count": 0,
    "unique_tools": [],
    "token_totals": {},
    "exit_code": 0,
}


def _resolve_cost(result: dict[str, Any]) -> None:
    """Resolve cost_usd + cost_source in place.

    Agent-reported cost wins whenever present (including a legitimate $0).
    Agents that don't know their cost MUST omit the key -- never write 0
    as a placeholder.

    ``cost_source`` is runner-only provenance per ``result.schema.json``.
    Idempotent on a fully resolved state (both keys set). An agent-supplied
    ``cost_source`` without ``cost_usd`` is the suppression spoof (write
    provenance to skip derivation); strip and re-resolve.
    """
    if result.get("cost_source") is not None:
        if result.get("cost_usd") is not None:
            return
        result.pop("cost_source", None)
    agent = result.get("cost_usd")
    if agent is not None:
        result["cost_usd"] = float(agent)
        result["cost_source"] = "agent"
        return
    result["cost_usd"], result["cost_source"] = derive_cost_from_totals(
        result.get("token_totals") or {}, result.get("model") or ""
    )


def utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    return str(value)


def normalize_agent_result(result: Optional[dict]) -> dict:
    """Validate + normalize an agent result against schemas/result.schema.json.

    Coerces ``None`` to type-safe defaults for typed fields, then resolves
    cost_usd / cost_source. Status defaults to ``"unknown"``.
    """
    normalized = dict(result or {})
    normalized.setdefault("status", "unknown")
    normalized.setdefault("turns_taken", 0)
    normalized["turns_taken"] = int(normalized["turns_taken"] or 0)
    for key, default in _RESULT_NULL_DEFAULTS.items():
        if normalized.get(key) is None:
            normalized[key] = default

    _resolve_cost(normalized)

    _RESULT_VALIDATOR.validate(normalized)
    return normalized


def _run_git_value(project_root: Path, args: list[str]) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(project_root)] + args,
            capture_output=True,
            text=True,
            check=True,
        )
        return (proc.stdout or "").strip()
    except Exception:
        return "unknown"


def _timing_summary_from_calls(calls: list[Any]) -> dict:
    if not calls:
        return {
            "total_llm_time": 0.0,
            "llm_call_count": 0,
            "p50": None,
            "p95": None,
            "max": None,
        }
    durations = sorted(call.duration for call in calls)
    n = len(durations)
    return {
        "total_llm_time": float(sum(durations)),
        "llm_call_count": n,
        "p50": float(durations[n // 2]),
        "p95": float(durations[int(n * 0.95)] if n > 1 else durations[0]),
        "max": float(durations[-1]),
    }


def _existing_path(path_value: Optional[str]) -> Optional[str]:
    if not path_value:
        return None
    candidate = Path(path_value)
    return str(candidate) if candidate.exists() else None


def _rel_if_exists(path: Path, logs_dir: Path) -> Optional[str]:
    """Relativized artifact pointer, or None when the file doesn't exist."""
    return relative_artifact_path(path, logs_dir) if path.exists() else None


# Maps artifact key → filename, and which workflows produce each file.
_SCORE_FILES: dict[str, tuple[str, set[str]]] = {
    "scores_json": ("scores.json", {"exploit"}),
    "synthetic_scores_json": ("synthetic_scores.json", {"exploit"}),
    "redteam_scores_json": ("redteam_scores.json", {"redteam"}),
}


def _score_files_for_workflow(workflow_name: str) -> list[str]:
    """Return filenames of score files produced by the given workflow."""
    return [
        filename
        for filename, workflows in _SCORE_FILES.values()
        if workflow_name in workflows
    ]


def _score_artifact_paths(
    workflow_name: str, logs_dir: Path, workflow: Any
) -> dict[str, Optional[str]]:
    """Return artifact pointers for only the score files this workflow produces."""
    app_dir = getattr(workflow, "app_dir", None)

    def _find(name: str) -> Optional[str]:
        log_copy = logs_dir / name
        if log_copy.exists():
            return str(log_copy)
        if app_dir and (app_dir / name).exists():
            return str(app_dir / name)
        return None

    return {
        key: _find(filename) if workflow_name in workflows else None
        for key, (filename, workflows) in _SCORE_FILES.items()
    }


def _detect_inconsistencies(
    outcome: str,
    exit_reason: str,
    run_result: dict,
    evaluation: dict,
    workflow_name: str,
) -> list:
    """Return a list of human-readable strings when sub-statuses disagree."""
    issues: list[str] = []
    agent_status = str(run_result.get("status", "unknown"))
    eval_score = evaluation.get("score") if isinstance(evaluation, dict) else None

    if agent_status in ("timeout", "error") and outcome == "success":
        issues.append(f"agent_status is '{agent_status}' but outcome is 'success'")
    if agent_status == "timeout" and exit_reason == "completed":
        issues.append("agent timed out but exit_reason is 'completed'")
    if agent_status in ("timeout", "error") and eval_score == 1:
        issues.append(f"agent_status is '{agent_status}' but evaluation scored 1")
    if outcome == "success" and eval_score is not None and eval_score != 1:
        issues.append(f"outcome is 'success' but evaluation score is {eval_score}")
    if (
        workflow_name == "redteam"
        and eval_score is None
        and (
            exit_reason in ("completed", "missing_evaluation")
            or exit_reason.endswith("_run_completed")
        )
    ):
        issues.append("redteam evaluation did not produce a score")
    return issues


def write_run_summary(
    *,
    project_root: Path,
    run_id: str,
    app_name: str,
    resolved: Optional[ResolvedRunnerConfig],
    config_input: RunnerConfig,
    config_path: Optional[Path],
    workflow,
    run_result: dict,
    evaluation: dict,
    outcome: str,
    exit_reason: str,
    started_at: str,
    ended_at: str,
    start_error_count: int,
    timing_start_idx: int,
) -> None:
    """Write run_summary.json from the resolved config (effective view).

    ``resolved`` is None only when resolution itself failed; in that case we
    skip the effective-view summary and write a minimal record from the input
    contract for forensics.
    """
    logs_dir = logger_manager.get_logs_dir()
    app_metadata = getattr(workflow, "metadata", {}) or {}

    git_status = _run_git_value(project_root, ["status", "--porcelain"])
    is_dirty = bool(git_status and git_status.strip())
    if is_dirty:
        diff = _run_git_value(project_root, ["diff", "HEAD"])
        try:
            with open(logs_dir / "git_repro.patch", "w", encoding="utf-8") as f:
                f.write(diff)
        except OSError as e:
            logger.warning("Failed to write git_repro.patch: %s", e)

    # Canonical path written by both custom and BYO; no agent-supplied field needed.
    canonical_conversation = logs_dir / "agent_run" / "conversation.jsonl"
    conversation_path = (
        str(canonical_conversation) if canonical_conversation.exists() else None
    )
    system_prompt_path = _existing_path(run_result.get("system_prompt_file"))

    token_usage_path = logs_dir / "agent_run" / "token_usage.jsonl"
    token_usage_path.parent.mkdir(parents=True, exist_ok=True)
    llm_calls_this_run = time_tracker.llm_calls[timing_start_idx:]

    unique_tools = run_result.get("unique_tools") or []
    if not isinstance(unique_tools, list):
        unique_tools = []

    token_totals = run_result.get("token_totals") or {}
    if not isinstance(token_totals, dict):
        token_totals = {}

    # Timing summary: prefer time_tracker data (one llm_timing call per
    # model request, recorded by the custom in-process provider). External
    # agents bypass time_tracker, so fall back to whatever timing dict the
    # agent surfaced — without this fallback their metrics would be zero.
    time_tracker_timing = _timing_summary_from_calls(llm_calls_this_run)
    agent_timing_raw = run_result.get("timing")
    agent_timing = agent_timing_raw if isinstance(agent_timing_raw, dict) else {}
    if llm_calls_this_run:
        timing_summary = {**agent_timing, **time_tracker_timing}
    else:
        timing_summary = agent_timing or time_tracker_timing

    scores = evaluation.get("scores") if isinstance(evaluation, dict) else {}

    # All scalar fields read off the input contract (same shape regardless
    # of whether resolution succeeded). Only ``effective_view`` requires the
    # resolved object — it's None on resolution failure.
    wf_in = config_input.workflow
    ag_in = config_input.agent
    workflow_family: str = "exploit" if wf_in.kind == "exploit" else "redteam"

    if hasattr(workflow, "app_dir"):
        for score_file in _score_files_for_workflow(workflow_family):
            src = workflow.app_dir / score_file
            if src.exists():
                try:
                    shutil.copy2(src, logs_dir / score_file)
                except Exception as e:
                    logger.warning("Failed to copy %s: %s", score_file, e)

    cost_usd = run_result.get("cost_usd")
    score_artifact_paths = {
        key: relative_artifact_path(path, logs_dir)
        for key, path in _score_artifact_paths(
            workflow_family, logs_dir, workflow
        ).items()
    }
    squid_access_log = logs_dir / "squid_access.log"
    squid_cache_log = logs_dir / "squid_cache.log"

    agent_image = run_result.get("agent_image") or ag_in.image
    agent_image_digest = run_result.get("agent_image_digest")
    # ``effective`` reflects the resolved DI object (bundle-resolved attacker_model
    # and all). When resolution failed (rare — only on submodule init / metadata
    # errors), we still write the input via ``full_snapshot`` for forensics.
    effective_view = resolved.summary_view() if resolved is not None else None

    run_summary = {
        "run_id": run_id,
        "outcome": outcome,
        "exit_reason": exit_reason,
        "timestamps": {
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_seconds": float(time_tracker.get_experiment_duration() or 0.0),
        },
        "context": {
            "app_name": app_name,
            "workflow": workflow_family,
            "vuln_id": (
                wf_in.synthetic_vuln_id
                if isinstance(
                    wf_in, (ExploitWorkflowInput, RedteamSyntheticWorkflowInput)
                )
                else None
            ),
            "task": (
                wf_in.task if isinstance(wf_in, RedteamZerodayWorkflowInput) else None
            ),
            "agent_mode": ag_in.mode,
            "agent_image": agent_image,
            "agent_image_digest": agent_image_digest,
            "model": ag_in.model,
        },
        "config": {
            "config_path": str(config_path) if config_path else None,
            "full_snapshot": config_input.model_dump(),
            "effective": effective_view,
        },
        "reproducibility": {
            "git_commit": _run_git_value(project_root, ["rev-parse", "HEAD"]),
            "git_branch": _run_git_value(
                project_root, ["rev-parse", "--abbrev-ref", "HEAD"]
            ),
            "git_dirty": is_dirty,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "metrics": {
            "turn_count": int(run_result.get("turns_taken") or 0),
            "tool_call_count": int(run_result.get("tool_call_count") or 0),
            "unique_tools": sorted({str(tool) for tool in unique_tools}),
            "error_count": max(0, logger_manager.get_error_count() - start_error_count),
            "token_totals": token_totals,
            "cost_usd": cost_usd,
            "cost_source": run_result.get("cost_source"),
            "timing": timing_summary,
        },
        "results": {
            "agent_status": str(run_result.get("status", "unknown")),
            "score": evaluation.get("score") if isinstance(evaluation, dict) else None,
            "status": (
                evaluation.get("status") if isinstance(evaluation, dict) else None
            ),
            "scores": scores,
            "inconsistencies": _detect_inconsistencies(
                outcome, exit_reason, run_result, evaluation, workflow_family
            ),
        },
        "artifacts": {
            "log_file": relative_artifact_path(
                logger_manager.get_log_file_name(), logs_dir
            ),
            "agent_log_file": relative_artifact_path(
                logger_manager.get_agent_log_file_name(), logs_dir
            ),
            "token_usage_jsonl": _rel_if_exists(token_usage_path, logs_dir),
            "conversation_jsonl": relative_artifact_path(conversation_path, logs_dir),
            "system_prompt_file": relative_artifact_path(system_prompt_path, logs_dir),
            "squid_access_log": _rel_if_exists(squid_access_log, logs_dir),
            "squid_cache_log": _rel_if_exists(squid_cache_log, logs_dir),
            **score_artifact_paths,
            "logs_dir": relative_artifact_path(logs_dir, logs_dir),
        },
        "app": app_metadata,
    }

    # Warn rather than raise — by this point the agent has already run; a
    # validation error here shouldn't lose the data we just collected.
    try:
        _RUN_SUMMARY_VALIDATOR.validate(run_summary)
    except jsonschema.ValidationError as e:
        logger.warning("run_summary schema validation failed: %s", e)
    try:
        _write_json_atomic(logs_dir / "run_summary.json", run_summary)
    except Exception as e:
        logger.warning("Failed to write run_summary.json: %s", e)
