import datetime
import json
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

import jsonschema

from utils.json_io import write_json_atomic as _write_json_atomic
from utils.logger import logger, logger_manager
from utils.time_tracker import time_tracker

# Field whose name ends in *_KEY/*_TOKEN/*_SECRET/PASSWORD is scrubbed before
# run_summary.json hits disk. End-anchored to avoid false positives on plural
# forms (max_model_response_tokens). Per-app prompt credentials are out of
# scope (design §4.4).
_SECRET_KEY_RE = re.compile(r"(_KEY|_TOKEN|_SECRET|PASSWORD)$", re.IGNORECASE)
_REDACTED = "<redacted>"


def _redact_for_persistence(value: Any) -> Any:
    """Walk value; replace any dict value whose key looks credential-ish."""
    if isinstance(value, dict):
        return {
            k: _REDACTED if _SECRET_KEY_RE.search(str(k)) else _redact_for_persistence(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact_for_persistence(v) for v in value]
    return value

try:
    from jsonschema import validate as _jsonschema_validate
except Exception:  # pragma: no cover
    _jsonschema_validate = None


_RESULT_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "result.schema.json"
with _RESULT_SCHEMA_PATH.open() as _f:
    _RESULT_SCHEMA: dict[str, Any] = json.load(_f)
_RESULT_VALIDATOR = jsonschema.Draft202012Validator(_RESULT_SCHEMA)
_RESULT_DEFAULTS: dict[str, Any] = {
    k: v["default"]
    for k, v in _RESULT_SCHEMA["properties"].items()
    if "default" in v
}


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

    Pads missing optional fields with schema defaults; accepts the legacy
    ``turns`` alias for ``turns_taken``. Status defaults to ``"unknown"`` so
    empty-dict callers (harness-internal short-circuits) pass validation.
    """
    normalized = dict(result or {})
    if "turns_taken" not in normalized and "turns" in normalized:
        normalized["turns_taken"] = normalized["turns"]
    normalized.setdefault("status", "unknown")
    normalized.setdefault("turns_taken", 0)
    normalized["turns_taken"] = int(normalized["turns_taken"] or 0)
    # Treat None and missing-key as equivalent for defaulted fields: an
    # agent that emits ``"final_message": None`` (custom path hits this when
    # max_iterations expires without a final submission) should normalize
    # to ``""`` so schema validation on a typed field passes.
    for key, default in _RESULT_DEFAULTS.items():
        if normalized.get(key) is None:
            normalized[key] = default
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

    conversation_path = logs_dir / "agent_run" / "conversation.jsonl"
    conversation_path.parent.mkdir(parents=True, exist_ok=True)
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

    # Cost: agents may surface it at run_result top-level OR nest it inside
    # token_totals (e.g. via TokenTracker). Top-level wins so an agent can
    # report a different number than the per-call sum (CLI subscription
    # cost vs. API-priced); falls back to nested so consumers always see a
    # populated metric when one exists.
    cost_top = run_result.get("cost_usd")
    cost_nested = (
        token_totals.get("cost_usd") if isinstance(token_totals, dict) else None
    )
    cost_usd = cost_top if cost_top is not None else cost_nested

    # Image identity: external path stamps these in run_result via
    # harness.byo_agent (from the live container handle); custom path snaps
    # the digest into workflow.agent_image_digest before agent_env cleanup
    # (see runner.py). write_run_summary runs after cleanup, so the snapshot
    # is the only path that survives.
    agent_image = run_result.get("agent_image") or getattr(config, "agent_image", None)
    agent_image_digest = run_result.get("agent_image_digest") or getattr(
        workflow, "agent_image_digest", None
    )

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
            "vuln_id": config.synthetic_vuln_id,
            "task": config.task,
            "agent_mode": config.agent_mode,
            "agent_image": agent_image,
            "agent_image_digest": agent_image_digest,
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
                outcome, exit_reason, run_result, evaluation, config.workflow
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
            "screenshots_dir": (
                str(logs_dir / "screenshots")
                if (logs_dir / "screenshots").is_dir()
                else None
            ),
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
        _write_json_atomic(
            logs_dir / "run_summary.json", _redact_for_persistence(run_summary)
        )
    except Exception as e:
        logger.warning("Failed to write run_summary.json: %s", e)
