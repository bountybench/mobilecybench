"""Sequential batch orchestration for ``runner.py``.

The normal runner remains the single-run execution path. This module owns the
batch-only planning and summary-writing layer, then invokes the supplied
single-run function once for each expanded app × matrix cell.
"""

from __future__ import annotations

import itertools
import json
import os
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from pydantic import TypeAdapter

from models.config import BatchSpec, RunnerConfig
from utils.logger import logger, logger_manager
from utils.run_artifacts import utc_now_iso

DEFAULT_BATCH_MATRIX = {
    "attacker_model": ["malicious_app", "remote_attacker"],
}


@dataclass(frozen=True)
class BatchJob:
    """One expanded app × matrix cell to execute as a normal runner invocation."""

    index: int
    app_name: str
    config: RunnerConfig
    overrides: dict[str, Any]


RunFunc = Callable[[RunnerConfig, str, Path, Optional[Path]], int]


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Configuration file not found: {path}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {path}: {e}")
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


def load_batch_config_parts(config_path: Path) -> tuple[dict[str, Any], BatchSpec]:
    """Return top-level RunnerConfig defaults plus the validated batch block."""
    payload = _read_json_file(config_path)
    payload.pop("$schema", None)
    batch_payload = payload.pop("batch", None)
    if batch_payload is None:
        raise ValueError("Batch mode requires a top-level 'batch' object in the config")
    if not isinstance(batch_payload, dict):
        raise ValueError("Top-level 'batch' must be a JSON object")
    return payload, BatchSpec(**batch_payload)


def config_file_has_batch(config_path: Path) -> bool:
    """Cheap probe used by the CLI to allow app-less batch invocations."""
    payload = _read_json_file(config_path)
    return isinstance(payload.get("batch"), dict)


def _resolve_catalog_path(project_root: Path, batch: BatchSpec) -> Path:
    catalog_path = Path(batch.app_catalog)
    if not catalog_path.is_absolute():
        catalog_path = project_root / catalog_path
    return catalog_path


def resolve_batch_apps(project_root: Path, batch: BatchSpec) -> list[str]:
    """Resolve ``batch.apps`` into the concrete app order to execute."""
    if isinstance(batch.apps, list):
        return list(batch.apps)

    catalog_path = _resolve_catalog_path(project_root, batch)
    catalog = _read_json_file(catalog_path)
    sets = catalog.get("sets")
    if not isinstance(sets, dict) or "in_scope" not in sets:
        raise ValueError(f"App catalog {catalog_path} does not define sets.in_scope")
    apps = sets["in_scope"]
    if not isinstance(apps, list) or not all(isinstance(app, str) for app in apps):
        raise ValueError(
            f"App catalog {catalog_path} sets.in_scope must be a string list"
        )
    if not apps:
        raise ValueError(f"App catalog {catalog_path} sets.in_scope must not be empty")
    return list(apps)


def _effective_batch_matrix(
    base_config_payload: dict[str, Any], batch: BatchSpec
) -> dict[str, list[Any]]:
    matrix = dict(batch.matrix or {})
    if (
        base_config_payload.get("workflow", "redteam") == "redteam"
        and base_config_payload.get("probe_only") is True
        and "attacker_model" not in matrix
        and not base_config_payload.get("attacker_model")
    ):
        return {
            **{field: list(values) for field, values in DEFAULT_BATCH_MATRIX.items()},
            **matrix,
        }
    return matrix


def _matrix_cells(matrix: dict[str, list[Any]]) -> list[dict[str, Any]]:
    if not matrix:
        return [{}]
    keys = list(matrix.keys())
    return [
        dict(zip(keys, values, strict=True))
        for values in itertools.product(*(matrix[key] for key in keys))
    ]


def _matches_exclude(
    app_name: str, expanded_payload: dict[str, Any], exclude_entry: dict[str, Any]
) -> bool:
    for field_name, expected in exclude_entry.items():
        actual = app_name if field_name == "app" else expanded_payload.get(field_name)
        if actual != expected:
            return False
    return True


def _coerce_runner_field_value(field_name: str, value: Any) -> Any:
    """Coerce a value with the same per-field type used by RunnerConfig."""
    field_info = RunnerConfig.model_fields.get(field_name)
    if field_info is None:
        return value
    try:
        return TypeAdapter(field_info.annotation).validate_python(value)
    except Exception:
        # Keep invalid values raw so exact-match excludes still work, and so
        # RunnerConfig can report the real validation error for non-excluded
        # cells.
        return value


def _exclude_entry_with_runner_types(exclude_entry: dict[str, Any]) -> dict[str, Any]:
    """Return an exclude entry normalized to RunnerConfig field types."""
    normalized: dict[str, Any] = {}
    for field_name, expected in exclude_entry.items():
        if field_name == "app":
            normalized[field_name] = expected
        else:
            normalized[field_name] = _coerce_runner_field_value(field_name, expected)
    return normalized


def _exclude_payload_with_runner_defaults(payload: dict[str, Any]) -> dict[str, Any]:
    """Return per-field values suitable for exclude matching.

    ``batch.exclude`` is expressed in terms of effective RunnerConfig values, not
    just the raw matrix payload. Apply RunnerConfig field defaults and per-field
    coercion before cross-field validation so excludes can also remove matrix
    cells that would otherwise be invalid (for example the default
    ``no_codebase=False`` plus ``apk_obfuscation='on'``).
    """
    normalized: dict[str, Any] = {}
    for field_name, field_info in RunnerConfig.model_fields.items():
        if field_name in payload:
            value = payload[field_name]
        elif not field_info.is_required():
            value = field_info.get_default(call_default_factory=True)
        else:
            continue

        normalized[field_name] = _coerce_runner_field_value(field_name, value)

    # Preserve any non-model keys so future callers don't lose exact-match
    # behavior for extra payload fields before RunnerConfig rejects them.
    for key, value in payload.items():
        normalized.setdefault(key, value)
    return normalized


def _resolve_app_axis(
    matrix: dict[str, list[Any]],
    project_root: Path,
    batch: BatchSpec,
) -> tuple[list[str], dict[str, list[Any]], bool]:
    """Return apps plus the remaining RunnerConfig matrix.

    ``batch.apps`` is the default app axis. ``batch.matrix.app`` is accepted as
    an alias for users who want every cycled field in one matrix block; when it
    is present it owns the app axis and ``batch.apps`` is not resolved.
    """
    if "app" not in matrix:
        return resolve_batch_apps(project_root, batch), matrix, False

    matrix = dict(matrix)
    app_values = matrix.pop("app")
    if not all(isinstance(app, str) and app for app in app_values):
        raise ValueError("batch.matrix.app values must be non-empty strings")
    return list(app_values), matrix, True


def expand_batch_jobs(
    base_config_payload: dict[str, Any],
    batch: BatchSpec,
    project_root: Path,
) -> list[BatchJob]:
    """Expand and validate all batch jobs before any side-effectful run starts."""
    base_config_payload = {
        key: value
        for key, value in base_config_payload.items()
        if key not in ("$schema", "batch")
    }
    matrix = _effective_batch_matrix(base_config_payload, batch)
    apps, matrix, app_from_matrix = _resolve_app_axis(matrix, project_root, batch)
    cells = _matrix_cells(matrix)
    exclude_entries = [
        _exclude_entry_with_runner_types(exclude_entry)
        for exclude_entry in batch.exclude
    ]

    jobs: list[BatchJob] = []
    errors: list[str] = []
    index = 1
    for app_name in apps:
        for overrides in cells:
            expanded = {**base_config_payload, **overrides}
            exclude_payload = _exclude_payload_with_runner_defaults(expanded)
            if any(
                _matches_exclude(app_name, exclude_payload, exclude_entry)
                for exclude_entry in exclude_entries
            ):
                continue
            try:
                config = RunnerConfig(**expanded)
            except ValueError as e:
                errors.append(f"app={app_name!r} overrides={overrides!r}: {e}")
                continue
            if any(
                _matches_exclude(app_name, config.model_dump(), exclude_entry)
                for exclude_entry in exclude_entries
            ):
                continue
            job_overrides = dict(overrides)
            if app_from_matrix:
                job_overrides = {"app": app_name, **job_overrides}
            jobs.append(
                BatchJob(
                    index=index,
                    app_name=app_name,
                    config=config,
                    overrides=job_overrides,
                )
            )
            index += 1

    if errors:
        joined = "\n".join(f"- {error}" for error in errors)
        raise ValueError(f"Invalid expanded batch config(s):\n{joined}")
    if not jobs:
        raise ValueError("Batch expansion produced zero jobs")
    return jobs


def _logs_base(project_root: Path) -> Path:
    if "MOBILECYBENCH_LOGS_DIR" in os.environ:
        return Path(os.environ["MOBILECYBENCH_LOGS_DIR"])
    return project_root / "logs"


def _read_run_summary(logs_dir: Optional[Path]) -> dict[str, Any]:
    if not logs_dir:
        return {}
    summary_path = logs_dir / "run_summary.json"
    if not summary_path.exists():
        return {}
    try:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_batch_summary(batch_dir: Path, summary: dict[str, Any]) -> None:
    batch_dir.mkdir(parents=True, exist_ok=True)
    (batch_dir / "batch_summary.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def _clear_per_job_process_caches() -> None:
    """Clear known process-global caches before a new batch cell starts.

    Batch mode intentionally runs sequential cells in one Python process. The
    normal single-run CLI gets a fresh interpreter each time, so clear caches
    that are keyed by per-job environment/config to preserve that behavior.
    Keep this best-effort and side-effect-light: only clear modules already
    imported by a previous cell rather than importing custom-agent modules just
    to clear them.
    """
    docker_ops = sys.modules.get("agent.custom.backend.docker_ops")
    get_token_truncator = getattr(docker_ops, "get_token_truncator", None)
    cache_clear = getattr(get_token_truncator, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()


def run_batch(
    base_config_payload: dict[str, Any],
    batch: BatchSpec,
    project_root: Path,
    *,
    run_func: RunFunc,
    config_path: Optional[Path] = None,
) -> int:
    """Run a batch plan sequentially as independent ``runner.py`` runs."""
    jobs = expand_batch_jobs(base_config_payload, batch, project_root)
    batch_id = str(uuid.uuid4())
    batch_dir = _logs_base(project_root) / "batches" / f"batch_{batch_id[:8]}"
    started_at = utc_now_iso()
    summary: dict[str, Any] = {
        "batch_id": batch_id,
        "status": "running",
        "started_at": started_at,
        "ended_at": None,
        "config_path": str(config_path) if config_path else None,
        "app_catalog": str(_resolve_catalog_path(project_root, batch)),
        "total_jobs": len(jobs),
        "completed_jobs": 0,
        "continue_on_failure": batch.continue_on_failure,
        "jobs": [],
    }
    _write_batch_summary(batch_dir, summary)

    previous_session_id = os.environ.get("MOBILECYBENCH_SESSION_ID")
    stopped_on_failure = False

    try:
        for job in jobs:
            _clear_per_job_process_caches()
            os.environ["MOBILECYBENCH_SESSION_ID"] = str(uuid.uuid4())

            # Initialize LoggerManager with the per-job config before logging.
            from utils.logger import get_logger_manager

            get_logger_manager(
                config=job.config.model_dump(),
                app_name=job.app_name,
                rename_existing_logs_dir=False,
            )
            logger.info(
                "Batch %s starting job %s/%s: app=%s overrides=%s",
                batch_id[:8],
                job.index,
                len(jobs),
                job.app_name,
                json.dumps(job.overrides, sort_keys=True),
            )

            exit_code = run_func(
                job.config,
                job.app_name,
                project_root,
                config_path,
            )

            logs_dir = logger_manager.get_logs_dir()
            run_summary = _read_run_summary(logs_dir)
            job_record = {
                "index": job.index,
                "app": job.app_name,
                "overrides": job.overrides,
                "run_id": logger_manager.get_run_id(),
                "logs_dir": str(logs_dir) if logs_dir else None,
                "run_summary": (
                    str(logs_dir / "run_summary.json") if logs_dir else None
                ),
                "exit_code": exit_code,
                "outcome": run_summary.get("outcome"),
                "exit_reason": run_summary.get("exit_reason"),
                "score": (
                    run_summary.get("results", {}).get("score") if run_summary else None
                ),
            }
            summary["jobs"].append(job_record)
            summary["completed_jobs"] = len(summary["jobs"])
            _write_batch_summary(batch_dir, summary)

            logger.info(
                "Batch %s finished job %s/%s: app=%s exit_code=%s outcome=%s",
                batch_id[:8],
                job.index,
                len(jobs),
                job.app_name,
                exit_code,
                job_record["outcome"],
            )
            logger_manager.print_error_summary()

            if exit_code != 0 and not batch.continue_on_failure:
                stopped_on_failure = True
                break
    finally:
        if previous_session_id is None:
            os.environ.pop("MOBILECYBENCH_SESSION_ID", None)
        else:
            os.environ["MOBILECYBENCH_SESSION_ID"] = previous_session_id

    failed = any(job["exit_code"] != 0 for job in summary["jobs"])
    if stopped_on_failure:
        summary["status"] = "stopped_on_failure"
    elif failed:
        summary["status"] = "failed"
    else:
        summary["status"] = "completed"
    summary["ended_at"] = utc_now_iso()
    summary["summary_path"] = str(batch_dir / "batch_summary.json")
    _write_batch_summary(batch_dir, summary)

    print(f"Batch summary: {batch_dir / 'batch_summary.json'}")
    return 1 if failed else 0
