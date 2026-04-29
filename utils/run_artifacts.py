import datetime
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

from utils.logger import logger, logger_manager
from utils.time_tracker import time_tracker

try:
    from jsonschema import validate as _jsonschema_validate
except Exception:  # pragma: no cover
    _jsonschema_validate = None


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
    normalized = dict(result or {})
    turns_taken = normalized.get("turns_taken")
    if turns_taken is None:
        turns_taken = normalized.get("turns", 0)

    if "agent_type" not in normalized:
        if isinstance(normalized.get("conversation_history"), list) and normalized.get(
            "conversation_history"
        ):
            normalized["agent_type"] = "codex"
        else:
            normalized["agent_type"] = "custom"
    normalized.setdefault("status", "unknown")
    normalized["turns_taken"] = int(turns_taken or 0)
    normalized.setdefault("tool_call_count", 0)
    normalized.setdefault("unique_tools", [])
    normalized.setdefault("token_totals", {})
    normalized.setdefault("conversation_file", None)
    normalized.setdefault("system_prompt_file", None)
    normalized.setdefault("conversation_history", [])
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


def load_schema(project_root: Path, schema_name: str) -> Optional[dict]:
    schema_path = project_root / "schemas" / schema_name
    if not schema_path.exists():
        return None
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def validate_schema(instance: dict, schema: Optional[dict], artifact_name: str) -> None:
    if not schema or _jsonschema_validate is None:
        return
    try:
        _jsonschema_validate(instance=instance, schema=schema)
    except Exception as e:
        logger.warning("%s schema validation failed: %s", artifact_name, e)


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


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


def _materialize_conversation_fallback(
    conversation_history: Any, logs_dir: Path, run_id: str, project_root: Path
) -> Optional[Path]:
    if not isinstance(conversation_history, list) or not conversation_history:
        return None

    conversation_path = logs_dir / "conversation.jsonl"
    schema = load_schema(project_root, "conversation_turn.schema.json")
    lines: list[str] = []
    for idx, entry in enumerate(conversation_history, start=1):
        if not isinstance(entry, dict):
            continue
        tool_outputs = entry.get("tool_outputs", [])
        if not isinstance(tool_outputs, list):
            tool_outputs = [tool_outputs]

        event = {
            "run_id": run_id,
            "turn_number": idx,
            "timestamp": utc_now_iso(),
            "role": "assistant",
            "response_id": entry.get("response_id"),
            "assistant_text": entry.get("final_output"),
            "reasoning_summary": entry.get("reasoning_summary"),
            "tool_calls": [],
            "observations": [
                {
                    "tool_call_id": None,
                    "type": "tool_output",
                    "content": str(tool_output),
                    "truncated": False,
                }
                for tool_output in tool_outputs
            ],
            "status": "ok",
        }
        validate_schema(event, schema, "conversation turn")
        lines.append(json.dumps(event, ensure_ascii=False))

    if not lines:
        return None

    conversation_path.parent.mkdir(parents=True, exist_ok=True)
    with open(conversation_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return conversation_path


def _existing_path(path_value: Optional[str]) -> Optional[str]:
    if not path_value:
        return None
    candidate = Path(path_value)
    return str(candidate) if candidate.exists() else None


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
    return issues


def write_run_summary(
    *,
    project_root: Path,
    run_id: str,
    app_name: str,
    config,
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
    logs_dir = logger_manager.get_logs_dir()
    app_metadata = getattr(workflow, "metadata", {}) or {}

    # Check for git dirty state
    git_status = _run_git_value(project_root, ["status", "--porcelain"])
    is_dirty = bool(git_status and git_status.strip())
    if is_dirty:
        try:
            diff = _run_git_value(project_root, ["diff", "HEAD"])
            with open(logs_dir / "git_repro.patch", "w", encoding="utf-8") as f:
                f.write(diff)
        except Exception:
            pass

    conversation_path = _existing_path(run_result.get("conversation_file"))
    system_prompt_path = _existing_path(run_result.get("system_prompt_file"))
    if conversation_path is None:
        fallback_path = _materialize_conversation_fallback(
            run_result.get("conversation_history"),
            logs_dir=logs_dir,
            run_id=run_id,
            project_root=project_root,
        )
        conversation_path = str(fallback_path) if fallback_path else None

    token_usage_path = logs_dir / "token_usage.jsonl"
    llm_calls_this_run = time_tracker.llm_calls[timing_start_idx:]

    unique_tools = run_result.get("unique_tools") or []
    if not isinstance(unique_tools, list):
        unique_tools = []

    token_totals = run_result.get("token_totals") or {}
    if not isinstance(token_totals, dict):
        token_totals = {}

    # Timing summary: prefer time_tracker data when the agent used the
    # custom provider (one llm_timing call per model request), otherwise
    # fall back to any timing dict the agent provided.  CLI-based agents
    # (codex, claude-code) bypass time_tracker entirely, so without this
    # fallback their timing metrics would always be zero.
    time_tracker_timing = _timing_summary_from_calls(llm_calls_this_run)
    agent_timing = run_result.get("timing") or {}
    if not isinstance(agent_timing, dict):
        agent_timing = {}
    if llm_calls_this_run:
        timing_summary = time_tracker_timing
        if agent_timing:
            timing_summary = {**agent_timing, **time_tracker_timing}
    else:
        timing_summary = agent_timing or time_tracker_timing

    scores = evaluation.get("scores") if isinstance(evaluation, dict) else {}

    # Copy the workflow's score file to logs directory for self-containment.
    # Only copy the file that belongs to THIS workflow — stale files from
    # previous runs of other workflows would be misleading.
    if hasattr(workflow, "app_dir"):
        for score_file in _score_files_for_workflow(config.workflow):
            src = workflow.app_dir / score_file
            if src.exists():
                dst = logs_dir / score_file
                try:
                    shutil.copy2(src, dst)
                except Exception as e:
                    logger.warning("Failed to copy %s: %s", score_file, e)

    # Cost: claude-code surfaces it at run_result top-level; the custom
    # and codex agents nest it inside token_totals via TokenTracker. Read
    # the top-level first (so an agent that wants to report a different
    # number — e.g. CLI-reported subscription cost vs. API-priced — wins),
    # then fall back to the nested value so downstream consumers always
    # see a populated metric when one exists.
    cost_top = run_result.get("cost_usd")
    cost_nested = (
        token_totals.get("cost_usd") if isinstance(token_totals, dict) else None
    )
    cost_usd = cost_top if cost_top is not None else cost_nested

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
            "workflow": config.workflow,
            "vuln_id": (
                config.synthetic_vuln_id if config.workflow == "exploit" else None
            ),
            "agent_type": run_result.get("agent_type", "custom"),
            "model": config.model,
        },
        "config": {
            "build_type": config.build_type,
            "dry_run": config.dry_run,
            "emulator_backend": config.emulator_backend,
            "emulator_display": config.emulator_display,
            "screenshot_mode": config.screenshot_mode,
            "max_iterations": config.max_iterations,
            "max_model_response_tokens": config.max_model_response_tokens,
            "reasoning_effort": config.reasoning_effort,
            "config_path": str(config_path) if config_path else None,
            "full_snapshot": config.model_dump(),
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
                outcome, exit_reason, run_result, evaluation
            ),
        },
        "artifacts": {
            "log_file": logger_manager.get_log_file_name(),
            "agent_log_file": logger_manager.get_agent_log_file_name(),
            "token_usage_jsonl": (
                str(token_usage_path) if token_usage_path.exists() else None
            ),
            "conversation_jsonl": conversation_path,
            "system_prompt_file": system_prompt_path,
            **_score_artifact_paths(config.workflow, logs_dir, workflow),
            "logs_dir": str(logs_dir),
        },
        "app": app_metadata,
    }

    validate_schema(
        run_summary,
        load_schema(project_root, "run_summary.schema.json"),
        "run summary",
    )
    try:
        _write_json_atomic(logs_dir / "run_summary.json", run_summary)
    except Exception as e:
        logger.warning("Failed to write run_summary.json: %s", e)
