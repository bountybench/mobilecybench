"""Python-side producer for the BYO task contract (schemas/task.schema.json)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "task.schema.json"
with _SCHEMA_PATH.open() as _f:
    _TASK_VALIDATOR = jsonschema.Draft202012Validator(json.load(_f))


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
        # `agent_timeout` is the legacy field name; phase 1.3 renames it.
        "agent_wallclock_seconds": config.agent_timeout,
        "reasoning_effort": config.reasoning_effort,
        "screenshot_mode": getattr(config, "screenshot_mode", None),
    }
    _TASK_VALIDATOR.validate(task)
    return task
