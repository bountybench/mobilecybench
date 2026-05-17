"""Python-side producer for the BYO task contract (schemas/task.schema.json)."""

from __future__ import annotations

from typing import Any

from utils.json_io import load_validator

_TASK_VALIDATOR = load_validator("task.schema.json")


def build_task_dict(
    *,
    config: Any,
    metadata: dict[str, Any],
    app_name: str,
    prompt: str,
    run_id: str,
    apk_relpath: str,
) -> dict[str, Any]:
    """Assemble + schema-validate the task.json dict for an external agent.

    Raises ``jsonschema.ValidationError`` on contract violation.
    """
    task: dict[str, Any] = {
        "run_id": run_id,
        "app_name": app_name,
        "workflow": config.workflow,
        "package_name": metadata["package_name"],
        "app_server": metadata.get("app_server") or "",
        "emulator_server": metadata.get("emulator_server") or "",
        "vuln_id": config.synthetic_vuln_id,
        "apk_relpath": apk_relpath,
        "no_codebase": config.no_codebase,
        "attacker_model": config.attacker_model or "",
        "model": config.model,
        "prompt": prompt,
        "agent_wallclock_seconds": config.agent_wallclock_seconds,
        "reasoning_effort": config.reasoning_effort,
        "screenshot_mode": getattr(config, "screenshot_mode", None),
    }
    _TASK_VALIDATOR.validate(task)
    return task
